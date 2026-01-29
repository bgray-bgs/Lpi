#!/usr/bin/env bash
# LPI Installer
# Version: 1.2.0
# Last updated: 2026-01-29
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "=== LPI Installer v1.2.0 ==="
echo "Repo: $REPO_ROOT"
echo

if [[ $EUID -ne 0 ]]; then
  echo "Please run as root:"
  echo "  sudo bash scripts/install.sh"
  exit 1
fi

echo "[1/6] Installing OS packages..."
apt update
apt install -y \
  python3-gpiozero \
  python3-pytz \
  python3-astral \
  python3-requests \
  python3-google-auth \
  git

echo "[2/6] Creating folders..."
mkdir -p /home/pi/pi_monitor_test

echo "[3/6] Copying scripts into /home/pi..."
# Expect these paths in repo:
#   pi/timer.py
#   pi/lighton.py
#   pi/lightoff.py
#   pi/pi_monitor_test/status_test.py
#   pi/pi_monitor_test/command_apply.py
#   pi/pi_monitor_test/firestore_upload_status.py

install -m 0755 "$REPO_ROOT/pi/timer.py" /home/pi/timer.py
install -m 0755 "$REPO_ROOT/pi/lighton.py" /home/pi/lighton.py
install -m 0755 "$REPO_ROOT/pi/lightoff.py" /home/pi/lightoff.py

install -m 0755 "$REPO_ROOT/pi/pi_monitor_test/status_test.py" /home/pi/pi_monitor_test/status_test.py
install -m 0755 "$REPO_ROOT/pi/pi_monitor_test/command_apply.py" /home/pi/pi_monitor_test/command_apply.py
install -m 0755 "$REPO_ROOT/pi/pi_monitor_test/firestore_upload_status.py" /home/pi/pi_monitor_test/firestore_upload_status.py

chown -R pi:pi /home/pi/pi_monitor_test || true
chown pi:pi /home/pi/timer.py /home/pi/lighton.py /home/pi/lightoff.py || true

echo "[4/6] Initializing override state..."
echo "auto" > /home/pi/override_mode.txt
chown pi:pi /home/pi/override_mode.txt || true

python3 - <<'PY'
import json, datetime
state = {"mode":"auto","set_at_local": datetime.datetime.now().isoformat()}
with open("/home/pi/override_state.json","w") as f:
    json.dump(state, f)
PY
chown pi:pi /home/pi/override_state.json || true

echo "[5/6] Setting device ID (dashboard name)..."
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

echo "[6/6] Installing cron jobs (root)..."
TMP_CRON="$(mktemp)"
crontab -l 2>/dev/null > "$TMP_CRON" || true

# Remove old lines if they exist (idempotent)
grep -v "pi_monitor_test/command_apply.py" "$TMP_CRON" | \
grep -v "pi_monitor_test/status_test.py" | \
grep -v "pi_monitor_test/firestore_upload_status.py" > "${TMP_CRON}.clean"
mv "${TMP_CRON}.clean" "$TMP_CRON"

cat >> "$TMP_CRON" <<'CRON'
* * * * * flock -n /tmp/cmd.lock /usr/bin/python3 /home/pi/pi_monitor_test/command_apply.py >> /home/pi/command_cron.log 2>&1
* * * * * sleep 10; flock -n /tmp/timer.lock /usr/bin/python3 /home/pi/pi_monitor_test/status_test.py >> /home/pi/status_cron.log 2>&1
*/5 * * * * sleep 20; flock -n /tmp/upload.lock /usr/bin/python3 /home/pi/pi_monitor_test/firestore_upload_status.py >> /home/pi/upload_cron.log 2>&1
CRON

crontab "$TMP_CRON"
rm -f "$TMP_CRON"

echo
echo "✅ Install complete."
echo "Next:"
echo "  1) Copy /home/pi/lpi_monitor.json onto the Pi and set permissions."
echo "  2) Wait ~1-5 minutes and check logs:"
echo "     tail -n 40 /home/pi/command_cron.log"
echo "     tail -n 40 /home/pi/status_cron.log"
echo "     tail -n 40 /home/pi/upload_cron.log"
