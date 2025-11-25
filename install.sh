#!/bin/bash
# NEXUS CONTROLLER - GITHUB INSTALLER

# 1. Check for Root
if [ "$EUID" -ne 0 ]; then
  echo "Error: Please run as root (sudo)."
  exit 1
fi

echo "[+] Installing Dependencies..."
if command -v apt-get &> /dev/null; then
    apt-get update -qq
    apt-get install -y python3 python3-flask curl
fi

# 2. Configuration
# We pull the main application directly from the repository
REPO_RAW="https://raw.githubusercontent.com/Andy71uk/nexus-controller/main"
APP_FILE="nexus_controller.py"
INSTALL_DIR=$(pwd)

echo "[+] Downloading Nexus Controller..."
curl -sL "$REPO_RAW/$APP_FILE" -o "$INSTALL_DIR/$APP_FILE"

# 3. Verify download
if [ ! -s "$INSTALL_DIR/$APP_FILE" ]; then
    echo "Error: Download failed. Please check your internet connection."
    exit 1
fi

# 4. Create System Service
echo "[+] Configuring Service..."
cat << SVC_EOF > "/etc/systemd/system/nexus_controller.service"
[Unit]
Description=Nexus Controller
After=network.target

[Service]
User=${SUDO_USER:-$USER}
WorkingDirectory=$INSTALL_DIR
ExecStart=/usr/bin/python3 $INSTALL_DIR/$APP_FILE
Restart=always
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
SVC_EOF

# 5. Start
echo "[+] Starting Nexus Controller..."
systemctl daemon-reload
systemctl enable nexus_controller
systemctl restart nexus_controller

IP=$(hostname -I | awk '{print $1}')
echo "SUCCESS! Nexus Controller is online."
echo "Access it at: http://$IP:5000"
