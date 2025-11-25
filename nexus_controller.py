import subprocess
import time
import os
import sys
import threading
import logging
import re
import base64
import urllib.request
import platform
import socket
from flask import Flask, render_template_string, request, jsonify, Response, session, redirect, url_for

# --- CRASH LOGGING ---
logging.basicConfig(filename='nexus_error.log', level=logging.DEBUG)

app = Flask(__name__)

# --- CONFIGURATION ---
PORT = 5000
VERSION = "5.2 (Recovery Link)"
PASSWORD = "nexus"  # <--- CHANGE THIS PASSWORD!
app.secret_key = "nexus-recovery-link-secure-key-v5-2"

# --- MINECRAFT CONFIGURATION ---
MC_SCREEN_NAME = "minecraft"
MC_PATH = "/opt/minecraft-java-server"
# set to "auto" to let Nexus find the user running java
MC_USER = "auto" 

# --- METADATA ---
DEVELOPER = "Andy71uk"
BUILD_DATE = "November 25, 2025"
COPYRIGHT = "© 2025 Nexus Systems. All rights reserved."

# --- GITHUB CONFIGURATION ---
GITHUB_RAW_URL = "https://raw.githubusercontent.com/Andy71uk/nexus-controller/main/nexus_controller.py"
GITHUB_INSTALLER_URL = GITHUB_RAW_URL.replace("nexus_controller.py", "install.sh")
GITHUB_RECOVERY_URL = GITHUB_RAW_URL.replace("nexus_controller.py", "recovery.sh")

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

def get_host_info():
    info = {}
    try: info['Hostname'] = socket.gethostname()
    except: pass
    try: 
        if os.path.exists("/etc/os-release"):
            with open("/etc/os-release") as f:
                for line in f:
                    if line.startswith("PRETTY_NAME="):
                        info['OS Distribution'] = line.split("=")[1].strip().strip('"')
                        break
        else: info['OS Distribution'] = platform.system()
    except: info['OS Distribution'] = "Unknown Linux"
    try: info['Kernel'] = platform.release()
    except: pass
    try: info['Arch'] = platform.machine()
    except: pass
    try: info['Python'] = sys.version.split()[0]
    except: pass
    try: info['Local IP'] = subprocess.check_output("hostname -I", shell=True).decode().strip().split()[0]
    except: pass
    return info

def get_system_stats():
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

    load = 0
    try:
        l1, l5, l15 = os.getloadavg()
        cores = os.cpu_count() or 1
        load = round((l1 / cores) * 100, 1)
    except: pass

    mem = 0; disk = 0; uptime = "Unknown"
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
        report.append({"name": "Internet Connectivity", "status": "PASS", "msg": "Online"})
    except:
        report.append({"name": "Internet Connectivity", "status": "FAIL", "msg": "Offline"})

    try:
        d = int(subprocess.check_output("df -h /", shell=True).decode().splitlines()[1].split()[4].replace("%",""))
        status = "PASS" if d < 90 else "FAIL"
        report.append({"name": "Root Filesystem", "status": status, "msg": f"{d}% Used"})
    except: pass

    try:
        m = subprocess.check_output("free -m", shell=True).decode().splitlines()[1].split()
        p = round((int(m[2])/int(m[1]))*100)
        status = "PASS" if p < 95 else "WARN"
        report.append({"name": "Memory Capacity", "status": status, "msg": f"{p}% Used"})
    except: pass

    try:
        s = subprocess.call(["systemctl", "is-active", "--quiet", "ssh"])
        status = "PASS" if s == 0 else "WARN"
        msg = "Running" if s == 0 else "Inactive"
        report.append({"name": "SSH Service", "status": status, "msg": msg})
    except: pass

    return report

# --- HELPER: Find Minecraft User ---
def get_mc_process_owner():
    try:
        # Find PID of server.jar
        pid = subprocess.check_output("pgrep -f server.jar", shell=True).decode().strip()
        if pid:
            # Get owner of that PID
            owner = subprocess.check_output(f"ps -o user= -p {pid}", shell=True).decode().strip()
            return owner, pid
    except: pass
    return None, None

# --- HTML Frontend ---
STYLE_CSS = """
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
    
    .health-grid { display: grid; gap: 10px; }
    .health-item { display: flex; align-items: center; justify-content: space-between; padding: 15px; background: #0f172a; border-radius: 5px; border-left: 4px solid #555; }
    .h-pass { border-left-color: var(--green); } .h-fail { border-left-color: var(--red); } .h-warn { border-left-color: var(--warn); }
    .badge { padding: 3px 8px; border-radius: 4px; font-size: 0.8rem; font-weight: bold; background: #333; color: white; }
    .badge.PASS { background: rgba(34, 197, 94, 0.2); color: var(--green); border: 1px solid var(--green); }
    .badge.FAIL { background: rgba(239, 68, 68, 0.2); color: var(--red); border: 1px solid var(--red); }
    .badge.WARN { background: rgba(234, 179, 8, 0.2); color: var(--warn); border: 1px solid var(--warn); }
    
    .info-box { background: #0f172a; padding:10px; border-radius:4px; border:1px solid #334155; }
    .info-label { font-size:0.7rem; color:#94a3b8; text-transform:uppercase; letter-spacing:1px; margin-bottom:3px; }
    .info-val { font-family:monospace; font-size:0.95rem; color:#e2e8f0; word-break:break-all; }

    .mc-group { margin-bottom: 15px; } .mc-label { color: #94a3b8; font-size:0.8rem; margin-bottom:5px; text-transform:uppercase; }
    .mc-btn-row { display:grid; grid-template-columns: repeat(auto-fill, minmax(120px, 1fr)); gap:8px; }
    .btn-mc { background: #2d2d2d; border: 1px solid #444; color: #eee; padding: 8px; border-radius: 4px; cursor: pointer; font-weight: bold; transition:0.2s; }
    .btn-mc:hover { background: #3d3d3d; border-color: var(--prim); }
    .mc-term { background: #101010; border: 1px solid #333; color: #aaa; height: 300px; overflow-y: auto; padding: 10px; font-family: monospace; font-size: 0.9rem; white-space: pre-wrap; display:flex; flex-direction:column-reverse; }

    .install-cmd { background: #000; color: #4ade80; padding: 15px; border-radius: 5px; font-family: monospace; margin: 15px 0; word-break: break-all; border: 1px solid #333; }
    
    .fill-green { background-color: var(--green); box-shadow: 0 0 5px var(--green); }
    .fill-warn { background-color: var(--warn); box-shadow: 0 0 5px var(--warn); }
    .fill-red { background-color: var(--red); box-shadow: 0 0 5px var(--red); }

    #update-banner { position: fixed; bottom: 20px; right: 20px; width: 300px; background: #1e293b; border: 1px solid var(--prim); border-radius: 8px; padding: 15px; box-shadow: 0 0 20px rgba(0,0,0,0.5); z-index: 200; display: none; flex-direction: column; gap: 10px; animation: slideUp 0.5s ease; }
    @keyframes slideUp { from { transform: translateY(100px); opacity: 0; } to { transform: translateY(0); opacity: 1; } }
    .upd-title { font-weight: bold; color: var(--prim); font-size: 1.1rem; }
    .upd-timer { font-size: 2rem; font-weight: bold; text-align: center; color: var(--text); margin: 10px 0; }
    .upd-actions { display: flex; gap: 10px; }

    @media(max-width:700px) { .grid-split { grid-template-columns: 1fr; } .stats { grid-template-columns: 1fr; } }
</style>
"""

HTML_HEADER = f"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>NEXUS | Control</title>
<link href="https://fonts.googleapis.com/css2?family=Orbitron:wght@700&family=Rajdhani:wght@500&display=swap" rel="stylesheet">
{STYLE_CSS}
</head>
"""

BODY = """
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
        <div class="brand">NEXUS <span style="color:var(--prim)">CONTROLLER</span> <span style="font-size:0.6em; opacity:0.5; vertical-align:middle; margin-left:5px;">{{ version }}</span></div>
        <div>
            <span id="up" style="font-family:monospace; margin-right:10px;">UP: --</span>
            <a href="/logout" style="color:var(--red); text-decoration:none; border:1px solid var(--red); padding:2px 8px; font-size:0.8rem;">LOGOUT</a>
        </div>
    </header>

    <div class="tabs">
        <button class="tab active" onclick="view('dash', this)">DASHBOARD</button>
        <button class="tab" onclick="view('minecraft', this)">MINECRAFT</button>
        <button class="tab" onclick="view('conn', this)">USERS</button>
        <button class="tab" onclick="view('logs', this)">WEB LOGS</button>
        <button class="tab" onclick="view('health', this)">SYSTEM HEALTH</button>
        <button class="tab" onclick="view('edit', this)">SETTINGS</button>
        <button class="tab" onclick="view('about', this)" style="margin-left:auto; border-color:transparent;">ABOUT</button>
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
                <button class="cmd-btn" onclick="run('sudo systemctl restart nexus_controller')">✨ Restart App</button>
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

    <!-- MINECRAFT -->
    <div id="minecraft" class="page">
        <div class="card" style="flex:1; display:flex; flex-direction:column;">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px;">
                <h3 style="margin:0; color:var(--prim);">Minecraft Console</h3>
                <div id="mc-status" style="font-weight:bold;">Checking...</div>
            </div>
            
            <div class="grid-split" style="height: 100%;">
                <div style="overflow-y:auto; padding-right:10px;">
                    <div style="margin-bottom:15px; font-size:0.8rem; color:#94a3b8;">
                        Active Screens: <span id="active-screens" style="color:#e2e8f0; font-family:monospace;">Scanning...</span>
                    </div>
                    <div style="margin-bottom:15px; font-size:0.8rem; color:#94a3b8;">
                        Process Owner: <span id="proc-owner" style="color:#e2e8f0; font-family:monospace;">Scanning...</span>
                    </div>
                    <div style="margin-bottom:15px; font-size:0.8rem; color:#94a3b8;">
                        Server Path: <span id="path-status" style="color:#e2e8f0; font-family:monospace;">Checking...</span>
                    </div>
                    
                    <div class="mc-group">
                        <div class="mc-label">VITAL COMMANDS</div>
                        <div class="mc-btn-row">
                            <button class="btn-mc" onclick="mcCmd('save-all')">Save All</button>
                            <button class="btn-mc" onclick="mcCmd('whitelist on')">Whitelist On</button>
                            <button class="btn-mc" onclick="mcCmd('whitelist off')">Whitelist Off</button>
                            <button class="btn-mc" style="color:#ef4444; border-color:#ef4444;" onclick="if(confirm('Stop Server?')) mcCmd('stop')">STOP SERVER</button>
                        </div>
                    </div>

                    <div class="mc-group">
                        <div class="mc-label">GEYSER / FLOODGATE</div>
                        <div class="mc-btn-row">
                            <button class="btn-mc" onclick="mcCmd('geyser reload')">Reload Geyser</button>
                            <button class="btn-mc" onclick="mcCmd('geyser offhand')">Offhand</button>
                        </div>
                    </div>

                    <div class="mc-group">
                        <div class="mc-label">GAMEPLAY</div>
                        <div class="mc-btn-row">
                            <button class="btn-mc" onclick="mcCmd('time set day')">Day</button>
                            <button class="btn-mc" onclick="mcCmd('time set night')">Night</button>
                            <button class="btn-mc" onclick="mcCmd('weather clear')">Clear Weather</button>
                            <button class="btn-mc" onclick="mcCmd('weather thunder')">Thunder</button>
                            <button class="btn-mc" onclick="mcCmd('kill @e[type=zombie]')">Kill Zombies</button>
                        </div>
                    </div>

                </div>
                
                <div style="display:flex; flex-direction:column; gap:10px; flex:1;">
                    <div class="mc-term" id="mc-log"><div>Loading logs...</div></div>
                    <div style="display:flex; gap:5px;">
                        <input id="mcin" type="text" placeholder="Console Command (e.g. op Steve)..." onkeypress="if(event.key=='Enter')doMcCmd()">
                        <button class="btn" style="width:auto" onclick="doMcCmd()">SEND</button>
                        <button class="btn" style="width:auto; background:#334155;" onclick="loadMcLog()">REFRESH LOG</button>
                    </div>
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
            <h3 style="margin-top:0; border-bottom:1px solid #334155; padding-bottom:10px; color:var(--prim); font-size:1rem;">HOST INFORMATION</h3>
            <div id="host-info-grid" style="display:grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap:10px; margin-bottom:20px;">
                <div style="color:#64748b;">Loading details...</div>
            </div>

            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:15px; border-top:1px solid #334155; padding-top:20px;">
                <h3 style="margin:0; color:var(--prim); font-size:1rem;">DIAGNOSTIC REPORT</h3>
                <button class="btn" style="width:auto;" onclick="runHealthCheck()">RUN DIAGNOSTICS</button>
            </div>
            <div id="health-results" class="health-grid">
                <div style="text-align:center; padding:20px; color:#64748b;">Click 'Run Diagnostics' to start scan.</div>
            </div>
        </div>
    </div>

    <!-- SETTINGS -->
    <div id="edit" class="page">
        <div class="card" style="flex:1; display:flex; flex-direction:column; justify-content:center; align-items:center; text-align:center;">
            <h2 style="color:var(--prim);">System Management</h2>
            <p style="color:#94a3b8; max-width:400px; margin-bottom:30px;">
                Updates are managed via GitHub. Push changes to your repository, then click the update button below.
            </p>
            <div style="display:flex; flex-direction:column; gap:15px; width:100%; max-width:300px;">
                <button class="btn" onclick="pullGithub()" style="background:#6366f1; color:#fff;">☁️ FORCE UPDATE FROM GITHUB</button>
                <button class="btn" onclick="openInstaller()" style="background:#4ade80; color:#000;">🔌 GENERATE INSTALLER COMMAND</button>
                <button class="btn" onclick="openRescue()" style="background:#eab308; color:#000;">🚑 GENERATE RESCUE TOOL</button>
            </div>
        </div>
    </div>

    <!-- ABOUT -->
    <div id="about" class="page">
        <div class="card" style="flex:1; display:flex; flex-direction:column; justify-content:center; align-items:center; text-align:center;">
            <h1 style="color:var(--prim); font-family:'Orbitron'; margin-bottom:10px;">NEXUS CONTROLLER</h1>
            <div style="color:var(--text); font-size:1.2rem; margin-bottom:5px;">{{ version }}</div>
            <div style="color:#94a3b8; margin-bottom:20px;">Build: {{ build_date }}</div>
            
            <div style="border-top:1px solid #334155; padding-top:20px; width:100%; max-width:400px;">
                <div style="color:#94a3b8; font-size:0.9rem; margin-bottom:5px;">DEVELOPER</div>
                <div style="font-size:1.1rem; font-weight:bold; margin-bottom:15px;">{{ developer }}</div>
                
                <div style="color:#64748b; font-size:0.8rem;">{{ copyright }}</div>
            </div>
        </div>
    </div>

    <!-- INSTALLER MODAL -->
    <div class="overlay" id="installModal" style="display:none;">
        <div class="box" style="width:500px; text-align:left;">
            <h3 style="margin-top:0; color:var(--prim);">Universal Installer</h3>
            <p>Run this command on any clean machine (Ubuntu, Debian, Pi) to install Nexus Controller from GitHub.</p>
            <div class="install-cmd" id="installCmd">Loading...</div>
            <div style="display:flex; gap:10px; justify-content:flex-end;">
                <button class="btn" style="background:transparent; border:1px solid #555;" onclick="document.getElementById('installModal').style.display='none'">CLOSE</button>
                <button class="btn" onclick="copyInstall()">COPY</button>
            </div>
        </div>
    </div>
    
    <!-- RECOVERY MODAL -->
    <div class="overlay" id="recoveryModal" style="display:none;">
        <div class="box" style="width:500px; text-align:left;">
            <h3 style="margin-top:0; color:var(--warn);">⚠️ EMERGENCY RECOVERY</h3>
            <p>If your server crashes or you get locked out, SSH in and run this command to install Safe Mode.</p>
            <div class="install-cmd" id="recoveryCmd">curl -sL {{ installer_url.replace("install.sh", "recovery.sh") }} | sudo bash</div>
            <div style="display:flex; gap:10px; justify-content:flex-end;">
                <button class="btn" style="background:transparent; border:1px solid #555;" onclick="document.getElementById('recoveryModal').style.display='none'">CLOSE</button>
                <button class="btn" onclick="copyRecovery()">COPY</button>
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

    <!-- RESTART OVERLAY -->
    <div class="overlay" id="restartModal" style="display:none; z-index:200;">
        <div class="box">
            <h3 style="margin-top:0; color:var(--green);">UPDATE SUCCESSFUL</h3>
            <p>The system is restarting with the new version.</p>
            <div style="font-size:3rem; font-weight:bold; margin:20px 0;" id="restartTimer">10</div>
            <p style="color:#94a3b8; font-size:0.9rem;">Reloading dashboard automatically...</p>
        </div>
    </div>
"""

SCRIPT = """
    <script>
        function view(id, el) {
            document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
            document.getElementById(id).classList.add('active');
            document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
            el.classList.add('active');
            if(id==='conn') getClients();
            if(id==='logs') getLogs();
            if(id==='health') loadSysInfo();
            if(id==='minecraft') loadMcLog();
        }

        function run(c) {
            document.getElementById('term').innerHTML = `<div>> ${c}</div>` + document.getElementById('term').innerHTML;
            fetch('/execute', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({cmd:c})})
            .then(r=>r.json()).then(d=>{
                document.getElementById('term').innerHTML = `<div style="color:${d.error?'#ef4444':'#4ade80'}">${d.output||d.error}</div>` + document.getElementById('term').innerHTML;
            });
        }
        function doCmd() { const i=document.getElementById('cin'); if(i.value){ run(i.value); i.value=''; } }

        function triggerRestart() {
            document.getElementById('restartModal').style.display = 'flex';
            let count = 10;
            const timer = document.getElementById('restartTimer');
            const interval = setInterval(() => {
                count--;
                timer.innerText = count;
                if (count <= 0) {
                    clearInterval(interval);
                    location.reload();
                }
            }, 1000);
        }

        function pullGithub() {
            fetch('/code/pull_github', {method:'POST'}).then(r=>r.json()).then(d=>{
                if(d.status === 'ok') {
                    triggerRestart();
                } else if (d.status === 'no_update') {
                    alert(d.message);
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

        function loadSysInfo() {
            fetch('/sysinfo').then(r=>r.json()).then(d=>{
                let h='';
                for(const [k, v] of Object.entries(d)) {
                    h += `<div class="info-box"><div class="info-label">${k}</div><div class="info-val">${v}</div></div>`;
                }
                document.getElementById('host-info-grid').innerHTML = h;
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

        // --- MINECRAFT FUNCTIONS ---
        function mcCmd(c) {
            const t = document.getElementById('mc-log');
            t.innerHTML = `<div style="color:#eab308">>> ${c}</div>` + t.innerHTML;
            fetch('/minecraft/cmd', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({cmd:c})})
            .then(r=>r.json()).then(d=>{
                if(d.error) alert(d.error);
            });
        }
        function doMcCmd() { const i=document.getElementById('mcin'); if(i.value){ mcCmd(i.value); i.value=''; } }

        function loadMcLog() {
            fetch('/minecraft/log').then(r=>r.json()).then(d=>{
                document.getElementById('mc-log').innerText = d.join('\\n');
            });
        }
        // Check Minecraft Status periodically
        setInterval(()=>{
            if(!document.getElementById('minecraft').classList.contains('active')) return;
            fetch('/minecraft/status').then(r=>r.json()).then(d=>{
                const s = document.getElementById('mc-status');
                if(d.running) {
                    s.innerHTML = `<span style="color:#22c55e">ONLINE</span> (RAM: ${d.mem} MB)`;
                } else {
                    s.innerHTML = `<span style="color:#ef4444">OFFLINE</span>`;
                }
                
                document.getElementById('active-screens').innerText = d.screens || 'No Sockets Found';
                document.getElementById('proc-owner').innerText = d.owner || 'Unknown';
                
                const ps = document.getElementById('path-status');
                ps.innerText = d.path_status;
                ps.style.color = d.path_status === "Valid" ? "#22c55e" : "#ef4444";
            });
        }, 5000);

        function openInstaller() {
            // We now use the pre-configured GitHub installer link
            const url = "{{ installer_url }}";
            document.getElementById('installCmd').innerText = `curl -sL ${url} | sudo bash`;
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
        
        function openRecovery() {
            document.getElementById('recoveryModal').style.display = 'flex';
        }

        function copyRecovery() {
            const txt = document.getElementById('recoveryCmd').innerText;
            if(navigator.clipboard) {
                navigator.clipboard.writeText(txt).then(()=>alert("Copied!"));
            } else {
                prompt("Copy this:", txt);
            }
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

FULL_HTML = f"{HTML_HEADER}{STYLE_CSS}{BODY}{SCRIPT}"

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
def home():
    # Pass the calculated installer URL to the template
    return render_template_string(FULL_HTML, 
        logged_in=session.get('logged_in'), 
        version=VERSION, 
        installer_url=GITHUB_INSTALLER_URL,
        build_date=BUILD_DATE,
        developer=DEVELOPER,
        copyright=COPYRIGHT
    )

@app.route('/login', methods=['POST'])
def login():
    if request.form.get('password') == PASSWORD:
        session['logged_in'] = True
        return redirect('/')
    return render_template_string(FULL_HTML, logged_in=False, error="INVALID PASSWORD", version=VERSION)

@app.route('/logout')
def logout(): session.clear(); return redirect('/')

@app.route('/status')
def status(): return jsonify(get_system_stats())

@app.route('/sysinfo')
def sysinfo(): return jsonify(get_host_info())

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

# --- MINECRAFT ROUTES ---
@app.route('/minecraft/cmd', methods=['POST'])
def mc_cmd():
    try:
        c = request.get_json().get('cmd')
        if not c: return jsonify({'error': 'Empty command'})
        
        if c.startswith('/'): c = c[1:]
        
        # Get dynamic user
        target_user = MC_USER
        if target_user == "auto":
             owner, _ = get_mc_process_owner()
             if owner: target_user = owner
             else: target_user = "root" # Fallback

        # Use double quotes and Carriage Return \r for reliable screen injection
        screen_cmd = f'screen -S {MC_SCREEN_NAME} -p 0 -X stuff "{c}\r"'
        
        if target_user != "root":
            # Wrap the screen command in sudo for the specific user
            final_cmd = f"sudo -u {target_user} {screen_cmd}"
        else:
            final_cmd = screen_cmd
            
        subprocess.run(final_cmd, shell=True)
        return jsonify({'status': 'ok'})
    except Exception as e:
        return jsonify({'error': str(e)})

@app.route('/minecraft/log')
def mc_log():
    # ATTEMPT TO FIND THE LOG FILE AUTOMATICALLY
    log_candidates = []
    
    # 1. Configured Path
    log_candidates.append(os.path.join(MC_PATH, "logs/latest.log"))

    # 2. Auto-Detect via Process
    try:
        # Find all PIDs matching "server.jar"
        pids = subprocess.check_output("pgrep -f server.jar", shell=True).decode().strip().split()
        for pid in pids:
            try:
                # Get Current Working Directory of the process
                cwd = subprocess.check_output(f"readlink -f /proc/{pid}/cwd", shell=True).decode().strip()
                log_candidates.append(os.path.join(cwd, "logs/latest.log"))
            except: pass
    except: pass

    # 3. Last Resort: Check user home folder
    try:
        home_logs = subprocess.check_output("find /home -name latest.log -path '*/logs/*' -print -quit", shell=True).decode().strip()
        if home_logs: log_candidates.append(home_logs)
    except: pass
    
    # 4. Explicit SFTP Path (user hint)
    log_candidates.append("/opt/minecraft-java-server/logs/latest.log")

    # Use the first one that actually exists
    final_path = None
    for p in log_candidates:
        if os.path.exists(p):
            final_path = p
            break
            
    if not final_path:
        return jsonify([f"Log file not found. Checked: {log_candidates}"])

    try:
        # Read last 50 lines
        output = subprocess.check_output(f"tail -n 50 '{final_path}'", shell=True).decode('utf-8', errors='ignore')
        return jsonify(output.strip().split('\n'))
    except Exception as e:
        return jsonify([str(e)])

@app.route('/minecraft/status')
def mc_status():
    try:
        # Check if java process for server.jar is running
        # We grep for server.jar (common name) or just java if fuzzy
        p = subprocess.check_output("pgrep -f server.jar", shell=True).decode().strip()
        
        # Get RAM usage if running
        mem = 0
        if p:
            try:
                # Get RSS memory in KB, convert to MB
                m = subprocess.check_output(f"ps -o rss= -p {p}", shell=True).decode().strip()
                mem = round(int(m) / 1024, 1)
            except: pass
            
        # Check screens
        screens = "No Sockets Found"
        owner = "Unknown"
        path_status = "Unknown"
        
        # Check Path Access
        if os.path.exists(MC_PATH):
             path_status = "Valid"
        else:
             path_status = f"Invalid Path: {MC_PATH}"

        try:
            # Get owner of the java process
            if p:
                owner = subprocess.check_output(f"ps -o user= -p {p}", shell=True).decode().strip()
        except: pass
        
        # Determine target user for screen check
        target_user = MC_USER
        if target_user == "auto" and owner != "Unknown":
            target_user = owner

        try:
            # Check screens for the specific user
            if target_user != "root":
                # Use -ls to list screens. We need to capture stdout even if it returns 1 (no screens)
                cmd = f"sudo -u {target_user} screen -ls"
                res = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
                out = res.stdout.decode().strip()
                if "No Sockets found" in out:
                     screens = f"No screens found for user '{target_user}'"
                elif res.returncode == 0:
                     screens = out
                else:
                     screens = f"Error checking screens for '{target_user}': {out}"
            else:
                 cmd = "screen -ls"
                 res = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
                 out = res.stdout.decode().strip()
                 if "No Sockets found" in out:
                      screens = "No screens found for user 'root'"
                 elif res.returncode == 0:
                      screens = out
                 else:
                      screens = f"Error checking screens: {out}"
        except Exception as e: 
             screens = f"Check Failed: {str(e)}"

        return jsonify({'running': True, 'pid': p, 'mem': mem, 'screens': screens, 'owner': owner, 'path_status': path_status})
    except:
        # Even if not running, check screens to debug
        screens = "Check Failed"
        owner = "None"
        path_status = "Unknown"
        if os.path.exists(MC_PATH): path_status = "Valid"
        else: path_status = f"Invalid: {MC_PATH}"
        
        try:
            target_user = MC_USER if MC_USER != "auto" else "root"
            if target_user != "root":
                cmd = f"sudo -u {target_user} screen -ls"
                res = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
                screens = res.stdout.decode().strip()
            else:
                cmd = "screen -ls"
                res = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
                screens = res.stdout.decode().strip()
            
            if "No Sockets found" in screens: screens = f"No screens found for user '{target_user}'"
        except: pass
        return jsonify({'running': False, 'pid': None, 'mem': 0, 'screens': screens, 'owner': owner, 'path_status': path_status})

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

        # 3. Version Check (NEW)
        match = re.search(r'VERSION\s*=\s*"(.*?)"', new_code)
        if match:
            remote_ver = match.group(1)
            if remote_ver == VERSION:
                return jsonify({'status': 'no_update', 'message': f'No updates available. Server is running {VERSION}'})

        with open(__file__, 'w') as f:
            f.write(new_code)
            
        def restart():
            time.sleep(1)
            # Renamed to match the file name change
            subprocess.run("sudo systemctl restart nexus_controller", shell=True)
            
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
        # UPDATED: Refers to nexus_controller.py and nexus_controller service
        rescue_script = f"""import os,sys,re,subprocess,base64; MAIN_FILE="nexus_controller.py"
def r(): open(MAIN_FILE,'w').write(re.sub(r'PASSWORD = ".*?"','PASSWORD = "nexus"',open(MAIN_FILE).read())); subprocess.run("sudo systemctl restart nexus_controller",shell=True)
def f(): open(MAIN_FILE,'wb').write(base64.b64decode("{b64_code}")); subprocess.run("sudo systemctl restart nexus_controller",shell=True)
c=input("1.Reset Pass 2.Factory Reset: "); r() if c=='1' else f() if c=='2' else None"""
        with open("nexus_rescue.py", "w") as f: f.write(rescue_script)
        return jsonify({'status': 'ok'})
    except Exception as e: return jsonify({'status': 'err', 'error': str(e)})

@app.route('/installer.sh')
def get_installer():
    try:
        with open(__file__, 'r') as f: current_code = f.read()
        # UPDATED: Installer now sets up nexus_controller.service and nexus_controller.py
        bash_script = f"""#!/bin/bash
if [ "$EUID" -ne 0 ]; then echo "Run as root"; exit 1; fi
if command -v apt-get &> /dev/null; then apt-get update -qq && apt-get install -y python3 python3-flask; fi
DIR=$(pwd); cat << 'PY_EOF' > "$DIR/nexus_controller.py"\n{current_code}\nPY_EOF
cat << SVC_EOF > "/etc/systemd/system/nexus_controller.service"
[Unit]\nDescription=Nexus Controller\nAfter=network.target
[Service]\nUser=${{SUDO_USER:-$USER}}\nWorkingDirectory=$DIR\nExecStart=/usr/bin/python3 $DIR/nexus_controller.py\nRestart=always\nEnvironment=PYTHONUNBUFFERED=1
[Install]\nWantedBy=multi-user.target\nSVC_EOF
systemctl daemon-reload && systemctl enable nexus_controller && systemctl restart nexus_controller
IP=$(hostname -I | awk '{{print $1}}'); echo "SUCCESS! http://$IP:5000"
"""
        return Response(bash_script, mimetype='text/plain')
    except Exception as e: return str(e), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=PORT, debug=True)
