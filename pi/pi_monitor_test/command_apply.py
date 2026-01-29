#!/usr/bin/env python3
# LPI Command Apply
# Version: 1.2.1
# Last updated: 2026-01-27
#
# Reads Firestore: device_commands/{device_id}.mode
# Writes local:
#   /home/pi/override_mode.txt
#   /home/pi/override_state.json (mode + set_at_local)
#
# IMPORTANT:
#   - set_at_local is only updated when the mode CHANGES.
#   - This enables auto-revert to work.

import os
import socket
import json
from datetime import datetime

import requests
from google.oauth2 import service_account
import google.auth.transport.requests

SERVICE_ACCOUNT_FILE = "/home/pi/lpi_monitor.json"
PROJECT_ID = "lpi-monitor"
COMMANDS_COLLECTION = "device_commands"
ID_FILE = "/home/pi/device_id.txt"

OVERRIDE_FILE = "/home/pi/override_mode.txt"
STATE_FILE = "/home/pi/override_state.json"

VALID_MODES = {"auto", "force_on", "force_off"}

def get_device_id() -> str:
    if os.path.exists(ID_FILE):
        with open(ID_FILE, "r") as f:
            v = f.read().strip()
            if v:
                return v
    return socket.gethostname()

def get_token() -> str:
    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE,
        scopes=["https://www.googleapis.com/auth/datastore"],
    )
    req = google.auth.transport.requests.Request()
    creds.refresh(req)
    return creds.token

def read_command_doc(device_id: str, token: str) -> dict:
    url = (
        f"https://firestore.googleapis.com/v1/projects/{PROJECT_ID}/databases/(default)"
        f"/documents/{COMMANDS_COLLECTION}/{device_id}"
    )
    r = requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=10)
    if r.status_code == 404:
        return {}
    r.raise_for_status()
    return r.json()

def get_field_string(fields: dict, name: str, default: str = "") -> str:
    v = fields.get(name, {})
    if "stringValue" in v:
        return v["stringValue"]
    return default

def read_current_state() -> dict:
    if not os.path.exists(STATE_FILE):
        return {}
    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f) or {}
    except Exception:
        return {}

def write_override_mode(mode: str) -> None:
    with open(OVERRIDE_FILE, "w") as f:
        f.write(mode + "\n")

def write_state(mode: str, set_at_local: str) -> None:
    with open(STATE_FILE, "w") as f:
        json.dump({"mode": mode, "set_at_local": set_at_local}, f)

def normalize_mode(mode: str) -> str:
    mode = (mode or "auto").strip().lower()
    if mode not in VALID_MODES:
        return "auto"
    return mode

def main():
    if not os.path.exists(SERVICE_ACCOUNT_FILE):
        print("❌ Missing service account file:", SERVICE_ACCOUNT_FILE)
        return

    device_id = get_device_id()
    current = read_current_state()
    current_mode = normalize_mode(current.get("mode", "auto"))
    current_set_at = current.get("set_at_local")

    try:
        token = get_token()
        doc = read_command_doc(device_id, token)
        fields = doc.get("fields", {}) if doc else {}
        new_mode = normalize_mode(get_field_string(fields, "mode", "auto") if fields else "auto")
    except Exception as e:
        print("❌ Failed reading Firestore mode:", e)
        return

    # Always write the simple mode file (cheap + keeps status_test robust)
    write_override_mode(new_mode)

    # Only update set_at_local when mode CHANGES (critical for auto-revert)
    if new_mode != current_mode or not current_set_at:
        set_at_local = datetime.now().isoformat()
        write_state(new_mode, set_at_local)
        print("Device:", device_id, "Override changed to:", new_mode, "set_at:", set_at_local)
    else:
        # Keep existing set_at_local
        write_state(current_mode, current_set_at)
        print("Device:", device_id, "Override unchanged:", new_mode)

if __name__ == "__main__":
    main()
