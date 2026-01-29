#!/usr/bin/env python3
# LPI Firestore Upload Status
# Version: 1.1.0
# Last updated: 2026-01-27

import json
import socket
import requests
import os
from datetime import datetime, timezone

from google.oauth2 import service_account
import google.auth.transport.requests

SERVICE_ACCOUNT_FILE = "/home/pi/lpi_monitor.json"
PROJECT_ID = "lpi-monitor"
COLLECTION = "devices"
LOCAL_STATUS_PATH = "/home/pi/pi_status.json"
ID_FILE = "/home/pi/device_id.txt"

def to_firestore_fields(d):
    def wrap(value):
        if isinstance(value, bool):
            return {"booleanValue": value}
        if isinstance(value, int):
            return {"integerValue": str(value)}
        if isinstance(value, float):
            return {"doubleValue": value}
        if isinstance(value, list):
            return {"arrayValue": {"values": [wrap(v) for v in value]}}
        if value is None:
            return {"nullValue": None}
        return {"stringValue": str(value)}
    return {"fields": {k: wrap(v) for k, v in d.items()}}

def main():
    if not os.path.exists(SERVICE_ACCOUNT_FILE):
        print("❌ Missing service account file:", SERVICE_ACCOUNT_FILE)
        return

    if os.path.exists(ID_FILE):
        with open(ID_FILE) as f:
            device_id = f.read().strip() or socket.gethostname()
    else:
        device_id = socket.gethostname()

    if not os.path.exists(LOCAL_STATUS_PATH):
        print("❌ No local status file at", LOCAL_STATUS_PATH)
        return

    with open(LOCAL_STATUS_PATH, "r") as f:
        status = json.load(f)

    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE,
        scopes=["https://www.googleapis.com/auth/datastore"],
    )
    auth_req = google.auth.transport.requests.Request()
    creds.refresh(auth_req)
    token = creds.token

    url = (
        f"https://firestore.googleapis.com/v1/projects/{PROJECT_ID}/databases/(default)"
        f"/documents/{COLLECTION}/{device_id}"
    )

    output_lines = status.get("stdout_lines") or status.get("script_output_lines", [])

    firestore_uploaded_at = datetime.now(timezone.utc).isoformat()
    local_last_updated = status.get("last_updated")

    # NEW: override mode from status JSON (set by status_test.py)
    override_mode = status.get("override_mode", "auto")

    payload = to_firestore_fields({
        "device_id": device_id,
        "reported_hostname": socket.gethostname(),

        "online": status.get("online", False),
        "timer_ok": status.get("timer_ok"),
        "return_code": status.get("return_code"),

        "last_updated": local_last_updated,
        "firestore_uploaded_at": firestore_uploaded_at,
        "local_last_updated": local_last_updated,

        "script_output_lines": output_lines,

        "stderr_lines": status.get("stderr_lines", []),
        "error": status.get("error"),

        # NEW: so dashboard can show/highlight active override without extra reads
        "override_mode": override_mode,
    })

    resp = requests.patch(
        url,
        headers={"Authorization": f"Bearer {token}"},
        json=payload,
        timeout=15,
    )

    print("HTTP", resp.status_code)
    if 200 <= resp.status_code < 300:
        print("✅ Uploaded status for", device_id)
        print("   override_mode:", override_mode)
        print("   local_last_updated:   ", local_last_updated)
        print("   firestore_uploaded_at:", firestore_uploaded_at)
    else:
        print("❌ Upload failed")
        print(resp.text)

if __name__ == "__main__":
    main()