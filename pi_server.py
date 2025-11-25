import subprocess
import time
import os
import sys
import threading
import logging
import re
import base64
import urllib.request
from flask import Flask, render_template_string, request, jsonify, Response, session, redirect, url_for

# --- CRASH LOGGING ---
logging.basicConfig(filename='nexus_error.log', level=logging.DEBUG)

app = Flask(__name__)

# --- CONFIGURATION ---
PORT = 5000
VERSION = "4.2 (GitHub Verified)" # <--- UPDATED VERSION NUMBER
PASSWORD = "nexus"  # <--- CHANGE THIS PASSWORD!
app.secret_key = "nexus-autopilot-secure-key-v4-2"

# [IMPORTANT] Paste your GitHub "Raw" link here:
GITHUB_RAW_URL = "https://raw.githubusercontent.com/Andy71uk/nexus-controller/main/pi_server.py"

# --- Global State ---
CLIENTS = {}

# --- Helper Functions ---
def get_os_from_ua(ua):
    ua = ua.lower()
    if 'windows' in ua: return 'Windows'
    if 'android' in ua: return 'Android'
    if 'iphone' in ua: return 'iOS'
    if 'macintosh' in ua: return 'macOS'
    if 'linux' in ua: return 'Linux'
    return 'Unknown'

def get_system_stats():
    # CPU Temp
    temp = 0
    try:
        r = subprocess.check_output("vcgencmd measure_temp", shell=True, stderr=subprocess.DEVNULL)
        temp = float(r.decode().replace("temp=","").replace("'C\n",""))
    except:
        try:
            with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
                val = float(f.read()) / 1000.0
                if val > 0: temp = round(val, 1)
        except: pass

    # CPU Load
    load = 0
    try:
        l1, l5, l15 = os.getloadavg()
        cores = os.cpu_count() or 1
        load = round((l1 / cores) * 100, 1)
    except: pass

    # Mem / Disk
    mem = 0
    disk = 0
    uptime = "Unknown"
    try:
        m = subprocess.check_output("free -m", shell=True).decode().splitlines()[1].split()
        mem = round((int(m[2])/int(m[1]))*100, 1)
        d = subprocess.check_output("df -h /", shell=True).decode().splitlines()[1].split()[4]
        disk = int(d.replace("%",""))
        uptime = subprocess.check_output("uptime -p", shell=True).decode().strip().replace("up ", "")
    except: pass

    return {"temp": temp, "load": load, "mem": mem, "disk": disk, "uptime": uptime}

def perform_health_check():
    report = []
    try:
        subprocess.check_call(["ping", "-c", "1", "-W", "1", "8.8.8.8"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        report.append({"name": "Internet Connectivity", "status": "PASS", "msg": "Online (Ping 8.8.8.8 OK)"})
    except:
        report.append({"name": "Internet Connectivity", "status": "FAIL", "msg": "Offline / Unreachable"})

    try:
        d = int(subprocess.check_output("df -h /", shell=True).decode().splitlines()[1].split()[4].replace("%",""))
        status = "PASS" if d < 90 else "FAIL"
        report.append({"name": "Root Filesystem", "status": status, "msg": f"{d}% Used (Threshold: 90%)"})
    except: pass

    try:
        m = subprocess.check_output("free -m", shell=True).decode().splitlines()[1].split()
        p = round((int(m[2])/int(m[1]))*100)
        status = "PASS" if p < 95 else "WARN"
        report.append({"name": "Memory Capacity", "status": status, "msg": f"{p}% Used (Threshold: 95%)"})
    except: pass

    try:
        stats = get_system_stats()
        t = stats['temp']
        if t > 0:
            status = "PASS" if t < 80 else "FAIL"
            report.append({"name": "Thermal Status", "status": status, "msg": f"{t}°C (Throttle Point: 80°C)"})
        else:
            report.append({"name": "Thermal Status", "status": "INFO", "msg": "No Sensor Detected (Virtual Machine?)"})
    except: pass

    try:
        s = subprocess.call(["systemctl", "is-active", "--quiet", "ssh"])
        status = "PASS" if s == 0 else "WARN"
        msg = "SSH Service Running" if s == 0 else "SSH Service Inactive"
        report.append({"name": "Remote Access (SSH)", "status": status, "msg": msg})
    except: pass

    return report

# --- HTML Frontend ---
HTML_HEADER = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>NEXUS | v4.2</title>
<link href="https://fonts.googleapis.com/css2?family=Orbitron:wght@700&family=Rajdhani:wght@500&display=swap" rel="stylesheet">
<style>
    :root { --bg: #0b1120; --panel: #1e293b; --text: #e2e8f0; --prim: #6366f1; --green: #22c55e; --red: #ef4444; --warn: #eab308; }
    body { background: var(--bg); color: var(--text); font-family: 'Rajdhani', sans-serif; margin: 0; padding: 10px; height: 100vh; display: flex; flex-direction: column; overflow: hidden; }
    
    /* Login */
    .overlay { position: fixed; top:0; left:0; width:100%; height:100%; background: var(--bg); z-index:99; display: flex; justify-content: center; align-items: center; }
    .box { background: var(--panel); padding: 30px; border: 1px solid var(--prim); border-radius: 10px; text-align: center; width: 300px; }
    input { background: #0f172a; border: 1px solid #334155; color: white; padding: 10px; width: 100%; margin-bottom: 10px; box-sizing: border-box; text-align: center; }
    .btn { background: var(--prim); color: white; border: none; padding: 10px 20px; cursor: pointer; font-weight: bold; width: 100%; }
    .btn:hover { opacity: 0.9; }
    .err { color: var(--red); margin-top: 10px; }

    /* App */
    header { display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #334155; padding-bottom: 10px; margin-bottom: 10px; }
    .brand { font-family: 'Orbitron'; font-size: 1.4rem; color: white; }
    .tabs { display: flex; gap: 5px; margin-bottom: 10px; flex-wrap: wrap; }
    .tab { background: transparent; border: 1px solid #334155; color: #94a3b8; padding: 8px 15px; cursor: pointer; font-weight: bold; }
    .tab.active { background: var(--prim); color: white; border-color: var(--prim); }
    
    .page { display: none; height: 100%; flex-direction: column; gap: 10px; flex: 1; min-height: 0; }
    .page.active { display: flex; }
    
    .stats { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 10px; }
    .card { background: var(--panel); padding: 10px; border-radius: 5px; border: 1px solid #334155; }
    .bar-bg { background: #334155; height: 5px; margin-top: 5px; }
    .bar-fill { background: var(--prim); height: 100%; width: 0%; transition: width 0.5s; }
    
    .grid-split { display: grid; grid-template-columns: 200px 1fr; gap: 10px; flex: 1; min-height: 0; }
    .cmds { display: flex; flex-direction: column; gap: 5px; overflow-y: auto; }
    .cmd-btn { background: #334155; border: none; color: white; padding: 10px; text-align: left; cursor: pointer; }
    .cmd-btn:hover { background: #475569; }
    .term { background: #000; flex: 1; border: 1px solid #334155; padding: 10px; overflow-y: auto; font-family: monospace; display: flex; flex-direction: column-reverse; color: #4ade80; }
    
    table { width: 100%; border-collapse: collapse; }
    td, th { text-align: left; padding: 8px; border-bottom: 1px solid #334155; }
    th { color: #94a3b8; font-size: 0.9rem; }
    
    textarea { flex: 1; background: #0f172a; color: #a5b4fc; border: 1px solid #334155; padding: 10px; font-family: monospace; resize: none; }
    
    /* Health Check Styles */
    .health-grid { display: grid; gap: 10px; }
    .health-item { display: flex; align-items: center; justify-content: space-between; padding: 15px; background: #0f172a; border-radius: 5px; border-left: 4px solid #555; }
    .h-pass { border-left-color: var(--green); }
    .h-fail { border-left-color: var(--red); }
    .h-warn { border-left-color: var(--warn); }
    .h-info { border-left-color: var(--prim); }
    .badge { padding: 3px 8px; border-radius: 4px; font-size: 0.8rem; font-weight: bold; background: #333; color: white; }
    .badge.PASS { background: rgba(34, 197, 94, 0.2); color: var(--green); border: 1px solid var(--green); }
    .badge.FAIL { background: rgba(239, 68, 68, 0.2); color: var(--red); border: 1px solid var(--red); }
    .badge.WARN { background: rgba(234, 179, 8, 0.2); color: var(--warn); border: 1px solid var(--warn); }

    /* Installer Modal */
    .install-cmd { background: #000; color: #4ade80; padding: 15px; border-radius: 5px; font-family: monospace; margin: 15px 0; word-break: break-all; border: 1px solid #333; }
    
    /* Dynamic Bar Colors */
    .fill-green { background-color: var(--green); box-shadow: 0 0 5px var(--green); }
    .fill-warn { background-color: var(--warn); box-shadow: 0 0 5px var(--warn); }
    .fill-red { background-color: var(--red); box-shadow: 0 0 5px var(--red); }

    /* Auto-Update Banner */
    #update-banner { position: fixed; bottom: 20px; right: 20px; width: 300px; background: #1e293b; border: 1px solid var(--prim); border-radius: 8px; padding: 15px; box-shadow: 0 0 20px rgba(0,0,0,0.5); z-index: 200; display: none; flex-direction: column; gap: 10px; animation: slideUp 0.5s ease; }
    @keyframes slideUp { from { transform: translateY(100px); opacity: 0; } to { transform: translateY(0); opacity: 1; } }
    .upd-title { font-weight: bold; color: var(--prim); font-size: 1.1rem; }
    .upd-timer { font-size: 2rem; font-weight: bold; text-align: center; color: var(--text); margin: 10px 0; }
    .upd-actions { display: flex; gap: 10px; }

    @media(max-width:700px) { .grid-split { grid-template-columns: 1fr; } .stats { grid-template-columns: 1fr; } }
</style>
</head>
"""

HTML_BODY = """
<body>
    {% if not logged_in %}
    <div class="overlay">
        <div class="box">
            <div class="brand" style="margin-bottom:20px;">NEXUS LOCKED</div>
            <form action="/login" method="POST">
                <input type="password" name="password" placeholder="Enter Password" autofocus>
                <button class="btn">UNLOCK</button>
            </form>
            {% if error %}<div class="err">{{ error }}</div>{% endif %}
        </div>
    </div>
    {% else %}
    
    <header>
        <div class="brand">NEXUS <span style="color:var(--prim)">CONTROLLER</span></div>
        <div>
            <span id="up" style="font-family:monospace; margin-right:10px;">UP: --</span>
            <a href="/logout" style="color:var(--red); text-decoration:none; border:1px solid var(--red); padding:2px 8px; font-size:0.8rem;">LOGOUT</a>
        </div>
    </header>

    <div class="tabs">
        <button class="tab active" onclick="view('dash', this)">DASHBOARD</button>
        <button class="tab" onclick="view('conn', this)">USERS</button>
        <button class="tab" onclick="view('logs', this)">WEB LOGS</button>
        <button class="tab" onclick="view('health', this)">SYSTEM HEALTH</button>
        <button class="tab" onclick="view('edit', this)">EDITOR</button>
    </div>

    <!-- DASHBOARD -->
    <div id="dash" class="page active">
        <div class="stats">
            <div class="card"><span id="lbl-cpu">CPU</span> <span id="t-cpu">--</span> <div class="bar-bg"><div id="b-cpu" class="bar-fill"></div></div></div>
            <div class="card">MEM <span id="t-mem">--</span> <div class="bar-bg"><div id="b-mem" class="bar-fill"></div></div></div>
            <div class="card">DISK <span id="t-dsk">--</span> <div class="bar-bg"><div id="b-dsk" class="bar-fill"></div></div></div>
        </div>
        <div class="grid-split">
            <div class="cmds card">
                <div style="color:#94a3b8; font-size:0.8rem; margin-bottom:5px;">ACTIONS</div>
                <button class="cmd-btn" onclick="run('sudo apt-get update')">⚡ Update System</button>
                <button class="cmd-btn" onclick="run('sudo systemctl restart pi_server')">✨ Restart App</button>
                <button class="cmd-btn" style="color:var(--red)" onclick="if(confirm('Reboot?')) run('sudo reboot')">🔄 Reboot</button>
            </div>
            <div style="display:flex; flex-direction:column; gap:5px; flex:1; min-height:0;">
                <div class="term" id="term"><div>Ready...</div></div>
                <div style="display:flex; gap:5px;">
                    <input id="cin" type="text" placeholder="Command..." onkeypress="if(event.key=='Enter')doCmd()">
                    <button class="btn" style="width:auto" onclick="doCmd()">RUN</button>
                </div>
            </div>
        </div>
    </div>

    <!-- CONNECTIONS -->
    <div id="conn" class="page">
        <div class="card" style="flex:1; overflow:auto;">
            <table>
                <thead><tr><th>IP</th><th>OS</th><th>STATUS</th></tr></thead>
                <tbody id="clist"></tbody>
            </table>
        </div>
    </div>

    <!-- WEB LOGS -->
    <div id="logs" class="page">
        <div class="card" style="flex:1; overflow:auto;">
            <button onclick="getLogs()" class="btn" style="margin-bottom:10px; width:auto; padding:5px 10px; font-size:0.8rem;">REFRESH</button>
            <table>
                <thead><tr><th>TIME</th><th>IP</th><th>REQ</th><th>CODE</th></tr></thead>
                <tbody id="llist"></tbody>
            </table>
        </div>
    </div>

    <!-- HEALTH CHECK -->
    <div id="health" class="page">
        <div class="card" style="flex:1; overflow:auto;">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:15px;">
                <h3 style="margin:0;">Diagnostic Report</h3>
                <button class="btn" style="width:auto;" onclick="runHealthCheck()">RUN DIAGNOSTICS</button>
            </div>
            <div id="health-results" class="health-grid">
                <div style="text-align:center; padding:20px; color:#64748b;">Click 'Run Diagnostics' to start scan.</div>
            </div>
        </div>
    </div>

    <!-- EDITOR -->
    <div id="edit" class="page">
        <div class="card" style="flex:1; display:flex; flex-direction:column;">
            <div style="display:flex; gap:10px; margin-bottom:10px;">
                <button class="btn" onclick="openInstaller()" style="background:#4ade80; color:#000;">🔌 INSTALLER</button>
                <button class="btn" onclick="pullGithub()" style="background:#6366f1; color:#fff;">☁️ UPDATE FROM GITHUB</button>
                <button class="btn" onclick="generateRescue()" style="background:#eab308; color:#000;">🚑 GENERATE RESCUE TOOL</button>
            </div>
            <textarea id="code" spellcheck="false"></textarea>
            <button class="btn" onclick="save()" style="margin-top:10px;">SAVE & RESTART</button>
        </div>
    </div>

    <!-- INSTALLER MODAL -->
    <div class="overlay" id="installModal" style="display:none;">
        <div class="box" style="width:500px; text-align:left;">
            <h3 style="margin-top:0; color:var(--prim);">Universal Installer</h3>
            <p>Run this command on any clean machine (Ubuntu, Debian, Pi) to install Nexus Controller instantly.</p>
            <div class="install-cmd" id="installCmd">Loading...</div>
            <div style="display:flex; gap:10px; justify-content:flex-end;">
                <button class="btn" style="background:transparent; border:1px solid #555;" onclick="document.getElementById('installModal').style.display='none'">CLOSE</button>
                <button class="btn" onclick="copyInstall()">COPY</button>
            </div>
        </div>
    </div>

    <!-- AUTO-UPDATE BANNER -->
    <div id="update-banner">
        <div class="upd-title">🚀 UPDATE DETECTED</div>
        <div style="font-size:0.9rem; color:#94a3b8;">New version: <span id="new-ver">...</span></div>
        <div class="upd-timer" id="upd-timer">60</div>
        <div class="upd-actions">
            <button class="btn" style="background:#334155;" onclick="postponeUpdate()">POSTPONE</button>
            <button class="btn" onclick="pullGithub()">UPDATE NOW</button>
        </div>
    </div>

    <script>
        function view(id, el) {
            document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
            document.getElementById(id).classList.add('active');
            document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
            el.classList.add('active');
            if(id==='edit') loadCode();
            if(id==='conn') getClients();
            if(id==='logs') getLogs();
        }

        function run(c) {
            document.getElementById('term').innerHTML = `<div>> ${c}</div>` + document.getElementById('term').innerHTML;
            fetch('/execute', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({cmd:c})})
            .then(r=>r.json()).then(d=>{
                document.getElementById('term').innerHTML = `<div style="color:${d.error?'#ef4444':'#4ade80'}">${d.output||d.error}</div>` + document.getElementById('term').innerHTML;
            });
        }
        function doCmd() { const i=document.getElementById('cin'); if(i.value){ run(i.value); i.value=''; } }

        function loadCode() { fetch('/code/read').then(r=>r.json()).then(d=>document.getElementById('code').value=d.code); }
        function save() {
            if(!confirm("Overwrite & Restart?")) return;
            fetch('/code/write', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({code:document.getElementById('code').value})})
            .then(()=>{ alert("Saved. Restarting..."); location.reload(); });
        }

        function pullGithub() {
            fetch('/code/pull_github', {method:'POST'}).then(r=>r.json()).then(d=>{
                if(d.status === 'ok') {
                    alert("Update successful! Restarting...");
                    location.reload();
                } else {
                    alert("Update failed: " + d.error);
                }
            });
        }

        function getClients() {
            fetch('/clients').then(r=>r.json()).then(d=>{
                let h=''; d.forEach(c=>h+=`<tr><td>${c.ip}</td><td>${c.os}</td><td style="color:${c.status=='Online'?'var(--green)':'#999'}">${c.status}</td></tr>`);
                document.getElementById('clist').innerHTML=h||'<tr><td>No active users</td></tr>';
            });
        }

        function getLogs() {
            fetch('/logs/web').then(r=>r.json()).then(d=>{
                let h=''; 
                if(!d.length || d[0].startsWith('No')) h='<tr><td colspan="4">No logs found</td></tr>';
                else d.forEach(l=>{
                    try {
                        const p=l.split(' '); 
                        h+=`<tr><td>${l.substring(l.indexOf('[')+1,l.indexOf(']'))}</td><td>${p[0]}</td><td>${l.substring(l.indexOf('"')+1,l.lastIndexOf('"')).substr(0,30)}...</td><td>${p[p.length-2]}</td></tr>`;
                    } catch(e){}
                });
                document.getElementById('llist').innerHTML=h;
            });
        }

        function runHealthCheck() {
            document.getElementById('health-results').innerHTML = '<div style="text-align:center; padding:20px;">Scanning system... <br> (This may take a few seconds)</div>';
            fetch('/health').then(r=>r.json()).then(data => {
                let html = '';
                data.forEach(item => {
                    let cls = 'h-info';
                    if(item.status === 'PASS') cls = 'h-pass';
                    if(item.status === 'FAIL') cls = 'h-fail';
                    if(item.status === 'WARN') cls = 'h-warn';
                    
                    html += `
                        <div class="health-item ${cls}">
                            <div>
                                <div style="font-weight:bold; margin-bottom:4px;">${item.name}</div>
                                <div style="font-size:0.9rem; color:#94a3b8;">${item.msg}</div>
                            </div>
                            <div class="badge ${item.status}">${item.status}</div>
                        </div>
                    `;
                });
                document.getElementById('health-results').innerHTML = html;
            });
        }

        function openInstaller() {
            const host = window.location.host;
            document.getElementById('installCmd').innerText = `curl -sL http://${host}/installer.sh | sudo bash`;
            document.getElementById('installModal').style.display = 'flex';
        }

        function copyInstall() {
            const txt = document.getElementById('installCmd').innerText;
            if(navigator.clipboard) {
                navigator.clipboard.writeText(txt).then(()=>alert("Copied!"));
            } else {
                prompt("Copy this:", txt);
            }
        }

        function generateRescue() {
            if(!confirm("Generate rescue tool?")) return;
            fetch('/rescue/generate', {method:'POST'}).then(r=>r.json()).then(d=>{
                alert(d.status === 'ok' ? "SUCCESS: 'nexus_rescue.py' created on server." : "Error: " + d.error);
            });
        }

        function setBar(id, val) {
            const el = document.getElementById(id);
            el.style.width = val + '%';
            el.className = 'bar-fill';
            if(val > 80) el.classList.add('fill-red');
            else if(val > 60) el.classList.add('fill-warn');
            else el.classList.add('fill-green');
        }

        // --- AUTO UPDATE LOGIC ---
        let updateTimer = null;
        let countdownVal = 60;
        let updatePostponed = false;

        function checkForUpdates() {
            if(updatePostponed) return;
            fetch('/update/check').then(r=>r.json()).then(d=>{
                if(d.update) showUpdateBanner(d.version);
            });
        }

        function showUpdateBanner(ver) {
            const b = document.getElementById('update-banner');
            if(b.style.display === 'flex') return; // Already showing
            b.style.display = 'flex';
            document.getElementById('new-ver').innerText = ver;
            
            countdownVal = 60;
            document.getElementById('upd-timer').innerText = countdownVal;
            
            if(updateTimer) clearInterval(updateTimer);
            updateTimer = setInterval(() => {
                countdownVal--;
                document.getElementById('upd-timer').innerText = countdownVal;
                if(countdownVal <= 0) {
                    clearInterval(updateTimer);
                    pullGithub(); // Perform update
                }
            }, 1000);
        }

        function postponeUpdate() {
            if(updateTimer) clearInterval(updateTimer);
            document.getElementById('update-banner').style.display = 'none';
            updatePostponed = true;
            // Reset postponement after 10 minutes
            setTimeout(() => { updatePostponed = false; }, 600000); 
        }

        // Check for updates every 5 minutes
        setInterval(checkForUpdates, 300000);
        // Check once on load
        setTimeout(checkForUpdates, 5000);

        setInterval(()=>{
            if(!document.getElementById('dash').classList.contains('active')) return;
            fetch('/status').then(r=>r.json()).then(d=>{
                document.getElementById('up').innerText="UP: "+d.uptime;
                
                // CPU Logic (Switch Label based on what we are measuring)
                const isTemp = d.temp > 0;
                document.getElementById('lbl-cpu').innerText = isTemp ? "CPU TEMP" : "CPU LOAD";
                const cpuVal = isTemp ? d.temp : d.load;
                document.getElementById('t-cpu').innerText = cpuVal + (isTemp ? "°C" : "%");
                setBar('b-cpu', isTemp ? (cpuVal/85)*100 : cpuVal); // 85C max for temp, 100% for load

                document.getElementById('t-mem').innerText = d.mem+'%';
                setBar('b-mem', d.mem);

                document.getElementById('t-dsk').innerText = d.disk+'%';
                setBar('b-dsk', d.disk);
            });
        }, 2000);
    </script>
    {% endif %}
</body>
</html>
"""

# --- Routes ---
@app.before_request
def check_auth():
    # Allow installer script without login
    if request.endpoint in ['static', 'login', 'get_installer']: return
    if not session.get('logged_in'):
        if request.endpoint == 'home': return
        return jsonify({'error': 'Login Required'}), 401

@app.before_request
def tracker():
    if request.endpoint == 'static': return
    CLIENTS[request.remote_addr] = {'seen': time.time(), 'ua': request.user_agent.string}

@app.route('/')
def home(): return render_template_string(HTML_HEADER + HTML_BODY, logged_in=session.get('logged_in'))

@app.route('/login', methods=['POST'])
def login():
    if request.form.get('password') == PASSWORD:
        session['logged_in'] = True
        return redirect('/')
    return render_template_string(HTML_HEADER + HTML_BODY, logged_in=False, error="INVALID PASSWORD")

@app.route('/logout')
def logout(): session.clear(); return redirect('/')

@app.route('/status')
def status(): return jsonify(get_system_stats())

@app.route('/execute', methods=['POST'])
def execute():
    try:
        c = request.get_json().get('cmd')
        o = subprocess.check_output(c, shell=True, stderr=subprocess.STDOUT).decode()
        return jsonify({'output': o})
    except Exception as e: return jsonify({'error': str(e)})

@app.route('/clients')
def clients():
    now = time.time()
    cl = []
    for ip, d in list(CLIENTS.items()):
        if now - d['seen'] > 60: del CLIENTS[ip]; continue
        cl.append({'ip': ip, 'os': get_os_from_ua(d['ua']), 'status': 'Online'})
    return jsonify(cl)

@app.route('/health')
def health(): return jsonify(perform_health_check())

@app.route('/logs/web')
def weblogs():
    logs = ['/var/log/apache2/access.log', '/var/log/nginx/access.log']
    for f in logs:
        if os.path.exists(f):
            try: return jsonify(subprocess.check_output(f"tail -n 20 {f}", shell=True).decode().strip().split('\n')[::-1])
            except: pass
    return jsonify(["No logs found"])

@app.route('/code/read')
def read(): return jsonify({'code': open(__file__).read()})

@app.route('/code/write', methods=['POST'])
def write():
    with open(__file__, 'w') as f: f.write(request.get_json()['code'])
    def restart(): time.sleep(1); subprocess.run("sudo systemctl restart pi_server", shell=True)
    threading.Thread(target=restart).start()
    return jsonify({'status': 'ok'})

@app.route('/code/pull_github', methods=['POST'])
def pull_github():
    try:
        # CACHE BUSTER: Add timestamp to URL to force fresh download
        url = f"{GITHUB_RAW_URL}?t={int(time.time())}"
        with urllib.request.urlopen(url) as response:
            new_code = response.read().decode('utf-8')
        
        # 1. Basic Content Check
        if "from flask import" not in new_code:
             return jsonify({'status': 'error', 'error': 'Invalid file content.'})

        # 2. Syntax Check (Prevent crashing the server with bad code)
        try:
            compile(new_code, '<string>', 'exec')
        except SyntaxError as e:
            return jsonify({'status': 'error', 'error': f'Syntax Error in GitHub code: Line {e.lineno}'})

        with open(__file__, 'w') as f:
            f.write(new_code)
            
        def restart():
            time.sleep(1)
            subprocess.run("sudo systemctl restart pi_server", shell=True)
            
        threading.Thread(target=restart).start()
        return jsonify({'status': 'ok'})
    except Exception as e:
        return jsonify({'status': 'error', 'error': str(e)})

@app.route('/update/check')
def check_update():
    try:
        # CACHE BUSTER here too
        url = f"{GITHUB_RAW_URL}?t={int(time.time())}"
        with urllib.request.urlopen(url) as response:
            remote_code = response.read().decode('utf-8')
        match = re.search(r'VERSION\s*=\s*"(.*?)"', remote_code)
        if match:
            remote_ver = match.group(1)
            if remote_ver != VERSION:
                return jsonify({'update': True, 'version': remote_ver})
        return jsonify({'update': False})
    except:
        return jsonify({'update': False})

@app.route('/code/raw')
def get_raw_code():
    try:
        with open(__file__, 'r') as f:
            return Response(f.read(), mimetype='text/plain')
    except Exception as e:
        return str(e), 500

@app.route('/rescue/generate', methods=['POST'])
def gen_rescue():
    try:
        with open(__file__, 'rb') as f: raw_bytes = f.read(); b64_code = base64.b64encode(raw_bytes).decode('utf-8')
        rescue_script = f"""import os,sys,re,subprocess,base64; MAIN_FILE="pi_server.py"
def r(): open(MAIN_FILE,'w').write(re.sub(r'PASSWORD = ".*?"','PASSWORD = "nexus"',open(MAIN_FILE).read())); subprocess.run("sudo systemctl restart pi_server",shell=True)
def f(): open(MAIN_FILE,'wb').write(base64.b64decode("{b64_code}")); subprocess.run("sudo systemctl restart pi_server",shell=True)
c=input("1.Reset Pass 2.Factory Reset: "); r() if c=='1' else f() if c=='2' else None"""
        with open("nexus_rescue.py", "w") as f: f.write(rescue_script)
        return jsonify({'status': 'ok'})
    except Exception as e: return jsonify({'status': 'err', 'error': str(e)})

@app.route('/installer.sh')
def get_installer():
    try:
        with open(__file__, 'r') as f: current_code = f.read()
        bash_script = f"""#!/bin/bash
if [ "$EUID" -ne 0 ]; then echo "Run as root"; exit 1; fi
if command -v apt-get &> /dev/null; then apt-get update -qq && apt-get install -y python3 python3-flask; fi
DIR=$(pwd); cat << 'PY_EOF' > "$DIR/pi_server.py"\n{current_code}\nPY_EOF
cat << SVC_EOF > "/etc/systemd/system/pi_server.service"
[Unit]\nDescription=Nexus Controller\nAfter=network.target
[Service]\nUser=${{SUDO_USER:-$USER}}\nWorkingDirectory=$DIR\nExecStart=/usr/bin/python3 $DIR/pi_server.py\nRestart=always\nEnvironment=PYTHONUNBUFFERED=1
[Install]\nWantedBy=multi-user.target\nSVC_EOF
systemctl daemon-reload && systemctl enable pi_server && systemctl restart pi_server
IP=$(hostname -I | awk '{{print $1}}'); echo "SUCCESS! http://$IP:5000"
"""
        return Response(bash_script, mimetype='text/plain')
    except Exception as e: return str(e), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=PORT, debug=True)
