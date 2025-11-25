NEXUS CONTROLLER

A lightweight, single-file, self-replicating control dashboard for Raspberry Pi and Linux Cloud Servers.

🚀 Overview

The Nexus Controller is a powerful web-based interface that provides monitoring, control, and diagnostics for Linux systems. It is designed as a Quine (a program that can edit its own source code), allowing it to update itself directly from GitHub without external package managers.

It works universally on:

Raspberry Pi: Displays hardware thermal data (vcgencmd).

Cloud Servers (VPS): Automatically switches to CPU Load monitoring.

✨ Features

🛡️ Security & Core

Secure Gateway: Password-protected login screen.

Crash Resilience: Automatic error logging and self-healing capabilities.

Rescue Kit: Generates a standalone emergency script (nexus_rescue.py) to reset passwords or fix broken code via SSH.

📊 Monitoring

Smart Dashboard: Live CPU, Memory, and Disk usage visualization.

Adaptive Sensors: Auto-detects hardware (Pi Temp vs. Server Load).

Network Intelligence: Tracks active users connected to the dashboard (IP, OS, Last Seen).

Web Traffic Inspector: Real-time view of Apache/Nginx visitor logs.

🔧 Management

System Controls: Update, Restart, Reboot, and Shutdown the server from the web.

Web Terminal: Execute shell commands directly from the browser.

System Health: One-click diagnostic audit (Internet, Disk Health, RAM Stress, Thermal Status, SSH).

☁️ Automation (The Factory)

Auto-Pilot Updates: Checks GitHub for new versions and alerts active users.

Universal Installer: Generates a single-line curl command to deploy the controller to any new machine instantly.

📥 Installation

Option 1: Universal Installer (Recommended)

Run this command on any fresh Raspberry Pi or Linux Server (Ubuntu/Debian):

curl -sL [https://raw.githubusercontent.com/Andy71uk/nexus-controller/main/pi_server.py](https://raw.githubusercontent.com//Andy71uk/nexus-controller/main/pi_server.py) | python3 -
# Note: You will need to set up the system service manually if running raw python, 
# or use the generated installer from an existing Nexus instance.


Option 2: Manual Setup

Install Dependencies:

sudo apt update
sudo apt install python3 python3-flask


Download Code:

wget [https://raw.githubusercontent.com/Andy71uk/nexus-controller/main/pi_server.py](https://raw.githubusercontent.com/Andy71uk/nexus-controller/main/pi_server.py)


Run:

sudo python3 pi_server.py


⚙️ Configuration

All configuration is done inside the file itself. Open pi_server.py to edit:

# Security Settings
PASSWORD = "nexus"          # Change this immediately!
app.secret_key = "..."      # Session key

# Auto-Update Source
GITHUB_RAW_URL = "[https://raw.githubusercontent.com/Andy71uk/nexus-controller/main/pi_server.py](https://raw.githubusercontent.com/Andy71uk/nexus-controller/main/pi_server.py)"


🚑 Recovery Mode

If you forget your password or the server crashes due to a bad update:

SSH into your server.

Run the rescue tool (if generated previously):

sudo python3 nexus_rescue.py


Select Option 1 to reset the password to nexus, or Option 2 to factory reset the code.

If you haven't generated the rescue tool yet, you can manually delete pi_server.py and re-download it.

📸 Screenshots

(Add screenshots of your dashboard here)
