#!/usr/bin/env bash
set -euo pipefail

echo "=== LPI Pi Monitor Installer ==="

# 1) Install packages
echo "[1/6] Installing packages..."
apt-get update
apt-get install -y \
  python3-gpiozero \
  python3-pytz \
  python3-astral \
  python3-requests \
  python3-google-auth \

# 2) Create folders
echo "[2/6] Creating folders..."
mkdir -p /home/pi/pi_monitor_test

# 3) Copy scripts into place
echo "[3/6] Copying scripts..."
install -m 0644 ./pi/timer.py /home/pi/timer.py
install -m 0644 ./pi/lighton.py /home/pi/lighton.py
install -m 0644 ./pi/lightoff.py /home/pi/lightoff.py
install -m 0644 ./pi/pi_monitor_test/status_test.py /home/pi/pi_monitor_test/status_test.py
install -m 0644 ./pi/pi_monitor_test/firestore_upload_status.py /home/pi/pi_monitor_test/firestore_upload_status.py

chown -R pi:pi /home/pi/pi_monitor_test
chown pi:pi /home/pi/timer.py /home/pi/lighton.py /home/pi/lightoff.py

# 4) Prompt for Device ID
echo "[4/6] Device ID setup..."
DEVICE_ID_FILE="/home/pi/device_id.txt"
default_id="$(hostname)"

echo "Device ID is shown in the dashboard and used as the Firestore document name."
read -r -p "Enter Device ID (default: ${default_id}): " device_id
device_id="${device_id:-$default_id}"
device_id="$(echo "$device_id" | tr -d '[:space:]')"

if [[ -z "$device_id" ]]; then
  echo "ERROR: Device ID cannot be empty."
  exit 1
fi
if ! [[ "$device_id" =~ ^[A-Za-z0-9._-]+$ ]]; then
  echo "ERROR: Device ID must be letters/numbers and . _ - only (no spaces)."
  exit 1
fi

echo "$device_id" > "$DEVICE_ID_FILE"
chown pi:pi "$DEVICE_ID_FILE"
chmod 0644 "$DEVICE_ID_FILE"
echo "✅ Wrote $DEVICE_ID_FILE = $device_id"

read -r -p "Set Linux hostname to '${device_id}' too? (y/N): " yn
if [[ "$yn" =~ ^[Yy]$ ]]; then
  hostnamectl set-hostname "$device_id"
  echo "✅ Hostname set to $device_id (reboot recommended)."
fi

# 5) GPIO group (redundant but fine)
echo "[5/6] GPIO permissions (safe redundancy)..."
usermod -aG gpio pi || true

# 6) Install cron (root)
echo "[6/6] Installing cron jobs..."
CRON_TMP="$(mktemp)"
crontab -l 2>/dev/null > "$CRON_TMP" || true

# Remove old entries we added before (idempotent)
grep -v "pi_monitor_test/status_test.py" "$CRON_TMP" | grep -v "pi_monitor_test/firestore_upload_status.py" > "${CRON_TMP}.clean" || true
mv "${CRON_TMP}.clean" "$CRON_TMP"

cat >> "$CRON_TMP" <<'CRON'
* * * * * flock -n /tmp/timer.lock /usr/bin/python3 /home/pi/pi_monitor_test/status_test.py >> /home/pi/status_cron.log 2>&1
*/5 * * * * test -f /home/pi/lpi_monitor.json && sleep 20; flock -n /tmp/upload.lock /usr/bin/python3 /home/pi/pi_monitor_test/firestore_upload_status.py >> /home/pi/upload_cron.log 2>&1
CRON

crontab "$CRON_TMP"
rm -f "$CRON_TMP"

echo ""
echo "=== Install complete ==="
echo "Next steps:"
echo "  1) Copy your service account key to: /home/pi/lpi_monitor.json"
echo "     then run:"
echo "       sudo chown root:root /home/pi/lpi_monitor.json"
echo "       sudo chmod 600 /home/pi/lpi_monitor.json"
echo ""
echo "  2) Test locally:"
echo "       sudo python3 /home/pi/pi_monitor_test/status_test.py"
echo "       cat /home/pi/pi_status.json"
echo ""
echo "  3) Test upload:"
echo "       sudo python3 /home/pi/pi_monitor_test/firestore_upload_status.py"
echo ""
