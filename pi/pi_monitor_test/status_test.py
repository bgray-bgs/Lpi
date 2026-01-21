import subprocess
import socket
import json
from datetime import datetime

# Get the Pi's hostname
hostname = socket.gethostname()

# Command to run your main script
COMMAND = ["/usr/bin/python3", "/home/pi/timer.py"]

print("Running command:", " ".join(COMMAND))

status = {
    "hostname": hostname,
    "last_updated": datetime.now().isoformat(),
}

try:
    result = subprocess.run(
        COMMAND,
        capture_output=True,
        text=True,
        timeout=55,  # prevents cron pileups if something hangs
    )

    stdout_lines = result.stdout.splitlines()
    stderr_lines = result.stderr.splitlines()

    ok = (result.returncode == 0)

    # Build status object
    status.update({
        # Backward-compatible fields (what you already had)
        "online": ok,
        "return_code": result.returncode,
        "script_output_lines": stdout_lines,  # keep this name for dashboard compat

        # New / richer fields (what uploader already tries to send)
        "timer_ok": ok,               # same meaning as online, but clearer name
        "stdout_lines": stdout_lines, # optional new key (uploader prefers this if present)
        "stderr_lines": stderr_lines, # huge help when something fails
        "error": None,                # reserved for wrapper errors (see except below)
    })

except subprocess.TimeoutExpired as e:
    # timer.py hung; treat as offline/error
    status.update({
        "online": False,
        "timer_ok": False,
        "return_code": 124,  # common "timeout" convention
        "script_output_lines": (e.stdout.splitlines() if e.stdout else []),
        "stdout_lines": (e.stdout.splitlines() if e.stdout else []),
        "stderr_lines": (e.stderr.splitlines() if e.stderr else []),
        "error": "timeout_expired",
    })

except Exception as e:
    # Wrapper itself failed (rare, but good to record)
    status.update({
        "online": False,
        "timer_ok": False,
        "return_code": 1,
        "script_output_lines": [],
        "stdout_lines": [],
        "stderr_lines": [],
        "error": f"status_test_exception: {type(e).__name__}: {e}",
    })

# Write to JSON
output_path = "/home/pi/pi_status.json"
with open(output_path, "w") as f:
    json.dump(status, f, indent=2)

print("Pi is online ✅" if status.get("online") else "Pi had an error ❌")
print("Hostname:", hostname)
print("Return code:", status.get("return_code"))
print("Status saved to:", output_path)

# Print a quick view of captured output
print("----- STDOUT (first 50 lines) -----")
for line in (status.get("stdout_lines") or [])[:50]:
    print(line)
if not (status.get("stdout_lines") or []):
    print("<empty>")

print("----- STDERR (first 50 lines) -----")
for line in (status.get("stderr_lines") or [])[:50]:
    print(line)
if not (status.get("stderr_lines") or []):
    print("<empty>")
