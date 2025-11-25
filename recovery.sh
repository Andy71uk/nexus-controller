#!/bin/bash
# NEXUS RECOVERY INSTALLER
# Usage: curl -sL https://raw.githubusercontent.com/Andy71uk/nexus-controller/main/recovery.sh | sudo bash

if [ "$EUID" -ne 0 ]; then
  echo "Error: Please run as root (sudo)."
  exit 1
fi

echo "========================================"
echo "      NEXUS EMERGENCY RECOVERY"
echo "========================================"

# 1. Stop the broken service
echo "[+] Stopping Nexus Service..."
systemctl stop nexus_controller

# 2. Install dependencies (just in case)
echo "[+] Verifying dependencies..."
if command -v apt-get &> /dev/null; then
    apt-get update -qq
    apt-get install -y python3 python3-flask curl
fi

# 3. Download the Safe Mode Python Script
INSTALL_DIR=$(pwd)
# If we are in root's home, try to find the actual install location
if [ "$INSTALL_DIR" == "/root" ]; then
    # Default to /home/pi or find where the service was pointing if possible
    # For safety, we'll default to the current user's directory who called sudo
    REAL_USER=${SUDO_USER:-$USER}
    if [ "$REAL_USER" != "root" ]; then
        INSTALL_DIR="/home/$REAL_USER"
    fi
fi

APP_FILE="nexus_controller.py"
RECOVERY_URL="https://raw.githubusercontent.com/Andy71uk/nexus-controller/main/recovery.py"

echo "[+] Downloading Safe Mode Controller to $INSTALL_DIR..."
curl -sL "$RECOVERY_URL" -o "$INSTALL_DIR/$APP_FILE"

# 4. Permission Fix
echo "[+] Fixing Permissions..."
chown ${SUDO_USER:-$USER} "$INSTALL_DIR/$APP_FILE"

# 5. Restart Service
echo "[+] Restarting Service in Safe Mode..."
systemctl daemon-reload
systemctl start nexus_controller

IP=$(hostname -I | awk '{print $1}')
echo "========================================"
echo "RECOVERY COMPLETE!"
echo "Access Safe Mode at: http://$IP:5000"
echo "========================================"
