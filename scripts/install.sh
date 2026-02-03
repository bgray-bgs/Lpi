#!/usr/bin/env bash
# LPI Installer
# Version: 1.2.5
# Last updated: 2026-02-03
#
# CHANGE (permissions only):
# - Ensure /home/pi/pi_status.json exists and is writable by user 'pi'
#   (status_test.py writes it, firestore_upload_status.py reads it)
# - No service changes
# - Cron timing remains as currently installed (15s command/status, 1m upload)

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "=== LPI Installer v1.2.5 ==="
echo "Repo: $REPO_ROOT"
echo

if [[ $EUID -ne 0 ]]; then
  echo "Please run as root:"
  echo "  sudo bash scripts/install.sh"
  exit 1
fi

echo "[1/7] Installing OS packages..."
apt update
apt install -y \
  git \
  cron \
  util-linux \
  python3-gpiozero \
  python3-pytz \
  python3-astral \
  python3-requests \
  python3-google-auth

echo "[2/7] Enabling cron service..."
systemctl enable --now cron >/dev/null 2>&1 || true

echo "[3/7] Creating folders..."
mkdir -p /home/pi/pi_monitor_test

echo "[4/7] Copying scripts into /home/pi..."
install -m 0755 "$REPO_ROOT/pi/timer.py" /home/pi/timer.py
install -m 0755 "$REPO_ROOT/pi/lighton.py" /home/pi/lighton.py
install -m 0755 "$REPO_ROOT/pi/lightoff.py" /home/pi/lightoff.py

install -m 0755 "$REPO_ROOT/pi/pi_monitor_test/status_test.py" /home/pi/pi_monitor_test/status_test.py
install -m 0755 "$REPO_ROOT/pi/pi_monitor_test/command_apply.py" /home/pi/pi_monitor_test/command_apply.py
install -m 0755 "$REPO_ROOT/pi/pi_monitor_test/firestore_upload_status.py" /home/pi/pi_monitor_test/firestore_upload_status.py

chown -R pi:pi /home/pi/pi_monitor_test || true
chown pi:pi /home/pi/timer.py /home/pi/lighton.py /home/pi/lightoff.py || true

# --- FIX: ensure pi can write status JSON (manual runs + avoids permission drift) ---
# status_test.py writes /home/pi/pi_status.json :contentReference[oaicite:2]{index=2}
# firestore_upload_status.py reads /home/pi/pi_status.json :contentReference[oaicite:3]{index=3}
echo "Ensuring /home/pi/pi_status.json is writable by pi..."
touch /home/pi/pi_status.json
chown pi:pi /home/pi/pi_status.json || true
chmod 664 /home/pi/pi_status.json || true

# Optional but harmless: ensure logs can be read easily
touch /home/pi/command_cron.log /home/pi/status_cron.log /home/pi/upload_cron.log
chown pi:pi /home/pi/command_cron.log /home/pi/status_cron.log /home/pi/upload_cron.log || true
chmod 664 /home/pi/command_cron.log /home/pi/status_cron.log /home/pi/upload_cron.log || true

echo "[5/7] Initializing override state..."
echo "auto" > /home/pi/override_mode.txt
chown pi:pi /home/pi/override_mode.txt || true

python3 - <<'PY'
import json, datetime
state = {"mode":"auto","set_at_local": datetime.datetime.now().isoformat()}
with open("/home/pi/override_state.json","w") as f:
    json.dump(state, f)
PY
chown pi:pi /home/pi/override_state.json || true

echo "[6/7] Setting device ID (dashboard name)..."
read -r -p "Enter device ID (example BGWebster): " DEVICE_ID
DEVICE_ID="${DEVICE_ID// /}"
if [[ -z "$DEVICE_ID" ]]; then
  echo "Device ID cannot be blank."
  exit 1
fi
echo "$DEVICE_ID" > /home/pi/device_id.txt
chown pi:pi /home/pi/device_id.txt || true
chmod 0644 /home/pi/device_id.txt

echo
echo "NOTE: You must place service account key at:"
echo "  /home/pi/lpi_monitor.json"
echo "and lock it down:"
echo "  sudo chown root:root /home/pi/lpi_monitor.json"
echo "  sudo chmod 600 /home/pi/lpi_monitor.json"
echo

echo "[7/7] Installing cron jobs (root)..."

TMP_CRON="$(mktemp)"
crontab -l 2>/dev/null > "$TMP_CRON" || true

# Remove any prior LPI lines safely
sed -i \
  -e '\#/home/pi/pi_monitor_test/command_apply.py#d' \
  -e '\#/home/pi/pi_monitor_test/status_test.py#d' \
  -e '\#/home/pi/pi_monitor_test/firestore_upload_status.py#d' \
  "$TMP_CRON"

# Append our lines (matches what you currently see in sudo crontab -l)
cat >> "$TMP_CRON" <<'CRON'
* * * * * flock -n /tmp/cmd.lock /usr/bin/python3 /home/pi/pi_monitor_test/command_apply.py >> /home/pi/command_cron.log 2>&1
* * * * * sleep 15; flock -n /tmp/cmd.lock /usr/bin/python3 /home/pi/pi_monitor_test/command_apply.py >> /home/pi/command_cron.log 2>&1
* * * * * sleep 30; flock -n /tmp/cmd.lock /usr/bin/python3 /home/pi/pi_monitor_test/command_apply.py >> /home/pi/command_cron.log 2>&1
* * * * * sleep 45; flock -n /tmp/cmd.lock /usr/bin/python3 /home/pi/pi_monitor_test/command_apply.py >> /home/pi/command_cron.log 2>&1

* * * * * sleep 10; flock -n /tmp/timer.lock /usr/bin/python3 /home/pi/pi_monitor_test/status_test.py >> /home/pi/status_cron.log 2>&1
* * * * * sleep 25; flock -n /tmp/timer.lock /usr/bin/python3 /home/pi/pi_monitor_test/status_test.py >> /home/pi/status_cron.log 2>&1
* * * * * sleep 40; flock -n /tmp/timer.lock /usr/bin/python3 /home/pi/pi_monitor_test/status_test.py >> /home/pi/status_cron.log 2>&1
* * * * * sleep 55; flock -n /tmp/timer.lock /usr/bin/python3 /home/pi/pi_monitor_test/status_test.py >> /home/pi/status_cron.log 2>&1

* * * * * sleep 20; flock -n /tmp/upload.lock /usr/bin/python3 /home/pi/pi_monitor_test/firestore_upload_status.py >> /home/pi/upload_cron.log 2>&1
CRON

crontab "$TMP_CRON"
rm -f "$TMP_CRON"

echo "✅ Root crontab installed."
echo
echo "Verify:"
echo "  sudo crontab -l"
echo
e
