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
VERSION = "5.2 (Permission Fix)"
PASSWORD = "nexus"  # <--- CHANGE THIS PASSWORD!
app.secret_key = "nexus-perm-fix-secure-key-v5-2"

# --- MINECRAFT CONFIGURATION ---
MC_SCREEN_NAME = "minecraft"
MC_PATH = "/opt/minecraft-java-server"
# set to "auto" to let Nexus find the user running java
MC_USER = "auto" 

# ... (Metadata section remains the same) ...
# --- Helper Functions ---
def get_os_from_ua(ua):
    ua = ua.lower()
    if 'windows' in ua: return 'Windows'
    if 'android' in ua: return 'Android'
    if 'iphone' in ua: return 'iOS'
    if 'macintosh' in ua: return 'macOS'
    if 'linux' in ua: return 'Linux'
    return 'Unknown'

def get_file_path():
    return os.path.abspath(__file__)

def safe_write_file(path, content):
    """Writes file, using sudo fallback if permission denied."""
    try:
        with open(path, 'w') as f:
            f.write(content)
        return True
    except PermissionError:
        try:
            # Fallback: Write to temp and sudo mv
            tmp_path = path + ".tmp"
            with open(tmp_path, 'w') as f:
                f.write(content)
            subprocess.run(f"sudo mv {tmp_path} {path}", shell=True, check=True)
            # Try to fix ownership to current user to avoid future sudo needs
            user = os.getenv('USER')
            if user: subprocess.run(f"sudo chown {user} {path}", shell=True)
            return True
        except Exception as e:
            logging.error(f"Safe write failed: {e}")
            return False

def get_host_info():

# ... (Rest of Helper Functions and HTML remain the same) ...
@app.route('/code/write', methods=['POST'])
def write_code():
    content = request.get_json()['code']
    if safe_write_file(get_file_path(), content):
        def restart(): time.sleep(1); subprocess.run("sudo systemctl restart nexus_controller", shell=True)
        threading.Thread(target=restart).start()
        return jsonify({'status': 'ok'})
    else:
        return jsonify({'error': 'Write failed (Permission Denied)'}), 500

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

        # 4. Safe Write (Handles Permissions)
        if safe_write_file(get_file_path(), new_code):
            def restart():
                time.sleep(1)
                subprocess.run("sudo systemctl restart nexus_controller", shell=True)
            threading.Thread(target=restart).start()
            return jsonify({'status': 'ok'})
        else:
            return jsonify({'status': 'error', 'error': 'Permission denied writing file.'})

    except Exception as e:
        return jsonify({'status': 'error', 'error': str(e)})

# ... (Update Check route remains the same) ...
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
        # UPDATED: Installer now fixes permissions immediately after creation
        bash_script = f"""#!/bin/bash
if [ "$EUID" -ne 0 ]; then echo "Run as root"; exit 1; fi
if command -v apt-get &> /dev/null; then apt-get update -qq && apt-get install -y python3 python3-flask; fi
DIR=$(pwd); cat << 'PY_EOF' > "$DIR/nexus_controller.py"\n{current_code}\nPY_EOF
# Fix permissions for the SUDO_USER
chown ${{SUDO_USER:-$USER}} "$DIR/nexus_controller.py"
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
