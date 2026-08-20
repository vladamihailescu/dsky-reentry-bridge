#!/bin/bash
# Sets up this Pi to run piDSKY_NASSP.py automatically on boot. Run this
# from wherever this repo got cloned to (it uses its own location as the
# install path, so no need to copy anything elsewhere first).
#
# What this does:
#   1. Enables I2C (needed for the Nextion display's SC16IS752 HAT)
#   2. Installs the udev rule that gives the Alert Lamps panel a stable
#      /dev/ttyAlarmPanel device path
#   3. Installs python3-serial and python3-evdev
#   4. Installs and enables a systemd service that runs piDSKY_NASSP.py
#      on every boot and restarts it if it crashes
#
# Safe to re-run - every step below only changes something if it isn't
# already in the state this script wants.

set -e

if [[ $EUID -eq 0 ]]; then
	echo "Don't run this as root/with sudo - it calls sudo itself where needed." >&2
	exit 1
fi

INSTALL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
echo "Installing from $INSTALL_DIR"

CONFIG_TXT=/boot/firmware/config.txt
if [[ ! -f "$CONFIG_TXT" ]]; then
	CONFIG_TXT=/boot/config.txt  # older Raspberry Pi OS releases
fi

echo "--- Enabling I2C (for the Nextion display's SC16IS752 HAT) ---"
if grep -q '^dtparam=i2c_arm=on' "$CONFIG_TXT" 2>/dev/null; then
	echo "Already enabled."
else
	echo "dtparam=i2c_arm=on" | sudo tee -a "$CONFIG_TXT" >/dev/null
fi
if grep -q '^dtoverlay=sc16is752-i2c' "$CONFIG_TXT" 2>/dev/null; then
	echo "SC16IS752 overlay already present."
else
	echo "dtoverlay=sc16is752-i2c,int_pin=24,addr=0x48" | sudo tee -a "$CONFIG_TXT" >/dev/null
	NEEDS_REBOOT=yes
fi

echo "--- Installing Alert Lamps panel udev rule ---"
sudo cp "$INSTALL_DIR/pi/99-dsky-alarm-panel.rules" /etc/udev/rules.d/99-dsky-alarm-panel.rules
sudo udevadm control --reload-rules
sudo udevadm trigger
# Gotcha (see project memory): if the panel was already plugged in before
# this rule existed, the symlink won't appear until a real unplug/replug -
# udevadm trigger alone doesn't generate a fresh "add" event for it.
echo "If /dev/ttyAlarmPanel doesn't show up, unplug and replug the Alert Lamps panel's USB cable."

echo "--- Installing Python packages ---"
sudo apt-get update -qq
sudo apt-get install -y python3-serial python3-evdev

echo "--- Installing the auto-start service ---"
SERVICE_FILE=/etc/systemd/system/dsky-reentry-bridge.service
sed -e "s#__INSTALL_DIR__#$INSTALL_DIR#g" -e "s#__USER__#$USER#g" \
	"$INSTALL_DIR/pi/dsky-reentry-bridge.service.template" | sudo tee "$SERVICE_FILE" >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable dsky-reentry-bridge.service
sudo systemctl restart dsky-reentry-bridge.service

echo ""
echo "Done. Check status any time with:"
echo "  systemctl status dsky-reentry-bridge"
echo "  journalctl -u dsky-reentry-bridge -f"
if [[ "$NEEDS_REBOOT" == "yes" ]]; then
	echo ""
	echo "I2C was just enabled for the first time - reboot before the Nextion display will work:"
	echo "  sudo reboot"
fi
