import subprocess
import time
import os
import sys
import threading
import urllib.request
from flask import Flask, render_template_string, request, jsonify

app = Flask(__name__)

# --- SAFE MODE CONFIG ---
PORT = 5000
VERSION = "SAFE MODE v1.0"
GITHUB_RAW_URL = "https://raw.githubusercontent.com/Andy71uk/nexus-controller/main/nexus_controller.py"

HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>NEXUS | Recovery</title>
<style>
    body { background: #1a0505; color: #e2e8f0; font-family: monospace; margin: 0; padding: 20px; display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100vh; }
    .box { background: #2d0a0a; border: 2px solid #ef4444; padding: 40px; border-radius: 10px; max-width: 500px; width: 100%; text-align: center; box-shadow: 0 0 50px rgba(239, 68, 68, 0.2); }
    h1 { color: #ef4444; margin-top: 0; }
    p { color: #999; margin-bottom: 30px; }
    .btn { display: block; width: 100%; padding: 15px; margin: 10px 0; background: #ef4444; color: white; border: none; border-radius: 5px; font-size: 1.1rem; font-weight: bold; cursor: pointer; transition: 0.2s; }
    .btn:hover { opacity: 0.9; }
    .btn-sec { background: #444; }
    .log { background: #000; color: #4ade80; padding: 15px; text-align: left; margin-top: 20px; border-radius: 5px; height: 150px; overflow-y: auto; border: 1px solid #333; font-size: 0.9rem; }
</style>
</head>
<body>
    <div class="box">
        <h1>⚠️ RECOVERY MODE</h1>
        <p>The Nexus Controller is running in Safe Mode. Use this interface to restore the full system.</p>
        
        <button class="btn" onclick="restore()">DOWNLOAD & INSTALL FULL VERSION</button>
        <button class="btn btn-sec" onclick="run('sudo reboot')">REBOOT SERVER</button>
        
        <div class="log" id="log">Waiting for action...</div>
    </div>

    <script>
        function log(msg) {
            const l = document.getElementById('log');
            l.innerHTML += '<div>> ' + msg + '</div>';
            l.scrollTop = l.scrollHeight;
        }

        function run(cmd) {
            log("Executing: " + cmd);
            fetch('/execute', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({cmd: cmd})
            }).then(r => r.json()).then(d => {
                if(d.output) log(d.output);
                if(d.error) log("ERROR: " + d.error);
            }).catch(e => log("Network Error"));
        }

        function restore() {
            if(!confirm("This will download the latest code from GitHub and overwrite this recovery mode. Continue?")) return;
            log("Downloading latest version...");
            fetch('/restore', {method: 'POST'}).then(r => r.json()).then(d => {
                if(d.status === 'ok') {
                    log("SUCCESS! Restarting service...");
                    setTimeout(() => { location.reload(); }, 5000);
                } else {
                    log("FAILED: " + d.error);
                }
            });
        }
    </script>
</body>
</html>
"""

@app.route('/')
def home(): return render_template_string(HTML)

@app.route('/execute', methods=['POST'])
def execute():
    try:
        cmd = request.get_json().get('cmd')
        o = subprocess.check_output(cmd, shell=True, stderr=subprocess.STDOUT).decode()
        return jsonify({'output': o})
    except subprocess.CalledProcessError as e: return jsonify({'error': e.output.decode()})
    except Exception as e: return jsonify({'error': str(e)})

@app.route('/restore', methods=['POST'])
def restore():
    try:
        # Download main controller code
        with urllib.request.urlopen(GITHUB_RAW_URL) as response:
            new_code = response.read().decode('utf-8')
        
        # Basic validation
        if "flask" not in new_code.lower():
            return jsonify({'status': 'error', 'error': 'Invalid file content'})

        # Overwrite self
        with open(__file__, 'w') as f:
            f.write(new_code)

        # Restart service
        def restart():
            time.sleep(1)
            subprocess.run("sudo systemctl restart nexus_controller", shell=True)
        
        threading.Thread(target=restart).start()
        return jsonify({'status': 'ok'})
    except Exception as e:
        return jsonify({'status': 'error', 'error': str(e)})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=PORT, debug=True)
