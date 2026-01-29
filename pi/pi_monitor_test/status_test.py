#!/usr/bin/env python3
# LPI Status Test (Override-aware + Auto-Revert)
# Version: 1.2.0
# Last updated: 2026-01-27

import subprocess
import socket
import json
import os
import datetime as dt
from datetime import datetime, timezone

import requests
import pytz
from astral.sun import sun
from astral import LocationInfo
from google.oauth2 import service_account
import google.auth.transport.requests

hostname = socket.gethostname()

TIMER_CMD = ["/usr/bin/python3", "/home/pi/timer.py"]
LIGHTON_CMD = ["/usr/bin/python3", "/home/pi/lighton.py"]
LIGHTOFF_CMD = ["/usr/bin/python3", "/home/pi/lightoff.py"]

OUTPUT_PATH = "/home/pi/pi_status.json"

# Override state files written by command_apply.py
OVERRIDE_FILE = "/home/pi/override_mode.txt"
STATE_FILE = "/home/pi/override_state.json"

# Firestore command doc (to clear mode back to auto)
SERVICE_ACCOUNT_FILE = "/home/pi/lpi_monitor.json"
PROJECT_ID = "lpi-monitor"
COMMANDS_COLLECTION = "device_commands"
ID_FILE = "/home/pi/device_id.txt"

# Must match timer intent
LIGHT_OFF_HOUR = 1  # 1:00 AM local
city = LocationInfo("Rochester", "USA", "America/New_York", 43.2086, -77.4623)


def get_device_id() -> str:
    if os.path.exists(ID_FILE):
        try:
            with open(ID_FILE, "r") as f:
                v = f.read().strip()
                if v:
                    return v
        except Exception:
            pass
    return socket.gethostname()


def run_and_capture(cmd):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=55)


def safe_localize(tz, naive_dt):
    try:
        return tz.localize(naive_dt, is_dst=None)
    except pytz.AmbiguousTimeError:
        return tz.localize(naive_dt, is_dst=False)
    except pytz.NonExistentTimeError:
        bumped = naive_dt + dt.timedelta(hours=1)
        return tz.localize(bumped, is_dst=None)


def read_override_mode() -> str:
    if not os.path.exists(OVERRIDE_FILE):
        return "auto"
    try:
        with open(OVERRIDE_FILE, "r") as f:
            v = f.read().strip().lower()
        if v in ("force_on", "force_off", "auto"):
            return v
    except Exception:
        pass
    return "auto"


def read_set_at_local(now_local: dt.datetime) -> dt.datetime:
    """
    Read when the override was set (local time). If missing, fall back to "now"
    (so we won't accidentally auto-revert immediately).
    """
    tz = now_local.tzinfo
    if not os.path.exists(STATE_FILE):
        return now_local
    try:
        with open(STATE_FILE, "r") as f:
            state = json.load(f)
        iso = state.get("set_at_local")
        if not iso:
            return now_local
        d = dt.datetime.fromisoformat(iso)
        if d.tzinfo is None:
            # assume local
            d = safe_localize(tz, d)
        return d.astimezone(tz)
    except Exception:
        return now_local


def write_override_mode(mode: str) -> None:
    mode = (mode or "auto").strip().lower()
    if mode not in ("force_on", "force_off", "auto"):
        mode = "auto"
    with open(OVERRIDE_FILE, "w") as f:
        f.write(mode + "\n")
    # also keep state file consistent
    try:
        with open(STATE_FILE, "w") as f:
            json.dump({"mode": mode, "set_at_local": datetime.now().isoformat()}, f)
    except Exception:
        pass


def get_token() -> str:
    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE,
        scopes=["https://www.googleapis.com/auth/datastore"],
    )
    req = google.auth.transport.requests.Request()
    creds.refresh(req)
    return creds.token


def patch_command_mode(device_id: str, mode: str) -> None:
    if not os.path.exists(SERVICE_ACCOUNT_FILE):
        return

    token = get_token()
    url = (
        f"https://firestore.googleapis.com/v1/projects/{PROJECT_ID}/databases/(default)"
        f"/documents/{COMMANDS_COLLECTION}/{device_id}"
    )

    now_utc = datetime.now(timezone.utc).isoformat()

    payload = {
        "fields": {
            "mode": {"stringValue": mode},
            "updated_at": {"stringValue": now_utc},
            "updated_by": {"stringValue": "auto_revert"},
        }
    }
    params = {"updateMask.fieldPaths": ["mode", "updated_at", "updated_by"]}

    try:
        r = requests.patch(
            url,
            headers={"Authorization": f"Bearer {token}"},
            params=params,
            json=payload,
            timeout=15,
        )
        if not (200 <= r.status_code < 300):
            print("WARN: auto_revert PATCH failed:", r.status_code, r.text)
    except Exception as e:
        print("WARN: auto_revert PATCH exception:", e)


def first_off_after(set_at_local: dt.datetime) -> dt.datetime:
    """First occurrence of LIGHT_OFF_HOUR after the override was set."""
    tz = set_at_local.tzinfo
    d = set_at_local.date()
    naive_today = dt.datetime.combine(d, dt.time(LIGHT_OFF_HOUR, 0))
    off_today = safe_localize(tz, naive_today)

    if set_at_local < off_today:
        return off_today

    naive_next = dt.datetime.combine(d + dt.timedelta(days=1), dt.time(LIGHT_OFF_HOUR, 0))
    return safe_localize(tz, naive_next)


def first_lighton_after(set_at_local: dt.datetime) -> dt.datetime:
    """First occurrence of (sunset - 1 hour) after the override was set."""
    tz = pytz.timezone(city.timezone)

    def lighton_for_date(d: dt.date) -> dt.datetime:
        s = sun(city.observer, date=d, tzinfo=tz)
        return s["sunset"] - dt.timedelta(hours=1)

    cand = lighton_for_date(set_at_local.date())
    if set_at_local < cand:
        return cand
    return lighton_for_date(set_at_local.date() + dt.timedelta(days=1))


# ---------------- Main ----------------
local_tz = pytz.timezone(city.timezone)
now_local = dt.datetime.now(local_tz)

status = {
    "hostname": hostname,
    "last_updated": datetime.now().isoformat(),
}

mode = read_override_mode()
set_at_local = read_set_at_local(now_local)
device_id = get_device_id()

auto_revert_msg = None

if mode == "force_on":
    cutoff = first_off_after(set_at_local)
    if now_local >= cutoff:
        write_override_mode("auto")
        patch_command_mode(device_id, "auto")
        mode = "auto"
        auto_revert_msg = f"AUTO-REVERT: force_on ended at off-time ({cutoff.strftime('%Y-%m-%d %H:%M:%S')})"

elif mode == "force_off":
    cutoff = first_lighton_after(set_at_local)
    if now_local >= cutoff:
        write_override_mode("auto")
        patch_command_mode(device_id, "auto")
        mode = "auto"
        auto_revert_msg = f"AUTO-REVERT: force_off ended at on-time ({cutoff.strftime('%Y-%m-%d %H:%M:%S')})"

status["override_mode"] = mode

try:
    extra_line = [auto_revert_msg] if auto_revert_msg else []

    if mode == "force_on":
        result = run_and_capture(LIGHTON_CMD)
    elif mode == "force_off":
        result = run_and_capture(LIGHTOFF_CMD)
    else:
        result = run_and_capture(TIMER_CMD)

    ok = (result.returncode == 0)
    stdout_lines = extra_line + result.stdout.splitlines()
    stderr_lines = result.stderr.splitlines()

    status.update({
        "online": ok,
        "return_code": result.returncode,
        "script_output_lines": stdout_lines,
        "timer_ok": ok,
        "stdout_lines": stdout_lines,
        "stderr_lines": stderr_lines,
        "error": None if ok else "run_failed",
    })

except subprocess.TimeoutExpired as e:
    status.update({
        "online": False,
        "timer_ok": False,
        "return_code": 124,
        "script_output_lines": (e.stdout.splitlines() if e.stdout else []),
        "stdout_lines": (e.stdout.splitlines() if e.stdout else []),
        "stderr_lines": (e.stderr.splitlines() if e.stderr else []),
        "error": "timeout_expired",
    })

except Exception as e:
    status.update({
        "online": False,
        "timer_ok": False,
        "return_code": 1,
        "script_output_lines": [],
        "stdout_lines": [],
        "stderr_lines": [],
        "error": f"status_test_exception: {type(e).__name__}: {e}",
    })

with open(OUTPUT_PATH, "w") as f:
    json.dump(status, f, indent=2)

print("Pi is online ✅" if status.get("online") else "Pi had an error ❌")
print("Hostname:", hostname)
print("Override mode:", mode)
print("Return code:", status.get("return_code"))
print("Status saved to:", OUTPUT_PATH)
