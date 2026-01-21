import json
import socket
import requests
import os
from datetime import datetime, timezone

from google.oauth2 import service_account
import google.auth.transport.requests

SERVICE_ACCOUNT_FILE = "/home/pi/lpi_monitor.json"
PROJECT_ID = "lpi-monitor"        # change if your project ID ever changes
COLLECTION = "devices"
LOCAL_STATUS_PATH = "/home/pi/pi_status.json"
ID_FILE = "/home/pi/device_id.txt"

def to_firestore_fields(d):
    """Convert a plain Python dict to Firestore REST 'fields' format."""
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
    # Basic file checks
    if not os.path.exists(SERVICE_ACCOUNT_FILE):
        print("❌ Missing service account file:", SERVICE_ACCOUNT_FILE)
        return

    # Pick device ID: prefer /home/pi/device_id.txt, else fallback to hostname
    if os.path.exists(ID_FILE):
        with open(ID_FILE) as f:
            device_id = f.read().strip()
        if not device_id:
            device_id = socket.gethostname()
    else:
        device_id = socket.gethostname()

    # Read local status JSON
    if not os.path.exists(LOCAL_STATUS_PATH):
        print("❌ No local status file at", LOCAL_STATUS_PATH)
        return

    with open(LOCAL_STATUS_PATH, "r") as f:
        status = json.load(f)

    # Build credentials and get access token
    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE,
        scopes=["https://www.googleapis.com/auth/datastore"],
    )
    auth_req = google.auth.transport.requests.Request()
    creds.refresh(auth_req)
    token = creds.token

    # Firestore document URL for this device
    url = (
        f"https://firestore.googleapis.com/v1/projects/{PROJECT_ID}/databases/(default)"
        f"/documents/{COLLECTION}/{device_id}"
    )

    # Choose output lines: prefer new key stdout_lines, fall back to old script_output_lines
    output_lines = status.get("stdout_lines")
    if not output_lines:
        output_lines = status.get("script_output_lines", [])

    # Heartbeat/staleness fields
    firestore_uploaded_at = datetime.now(timezone.utc).isoformat()
    local_last_updated = status.get("last_updated")

    # Prepare payload
    payload = to_firestore_fields({
        "device_id": device_id,
        "reported_hostname": socket.gethostname(),

        # Keep old 'online' so dashboard continues to work
        "online": status.get("online", False),

        # Add richer fields for debugging/visibility
        "timer_ok": status.get("timer_ok"),
        "return_code": status.get("return_code"),

        # Keep existing last_updated (this is the LOCAL script run time)
        "last_updated": local_last_updated,

        # NEW: upload timestamp (lets you detect "Pi is fine but upload is stale")
        "firestore_uploaded_at": firestore_uploaded_at,
        "local_last_updated": local_last_updated,

        # Dashboard output (compat): keep field name 'script_output_lines'
        "script_output_lines": output_lines,

        # New fields (optional for dashboard, great for troubleshooting)
        "stderr_lines": status.get("stderr_lines", []),
        "error": status.get("error"),
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
        print("   local_last_updated:   ", local_last_updated)
        print("   firestore_uploaded_at:", firestore_uploaded_at)
    else:
        print("❌ Upload failed")
        print(resp.text)

if __name__ == "__main__":
    main()
