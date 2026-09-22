#!/usr/bin/env python
"""Stop Qwen Image Runner: graceful quit via the app's own API, taskkill as fallback."""
from __future__ import annotations

import json
import subprocess
import sys
import time
import urllib.error
import urllib.request

try:  # Windows consoles may default to cp437/cp1252
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

APP_URL = "http://127.0.0.1:7878"


def get_json(url: str, timeout: float = 3.0):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode())


def main() -> int:
    try:
        meta = get_json(APP_URL + "/api/meta")
    except Exception:
        print("Qwen Image Runner is not running.")
        return 0
    if meta.get("app") != "Qwen Image Runner":
        print("Port 7878 is used by a different process - not touching it.")
        return 1
    pid = meta.get("pid")
    csrf = meta.get("csrf", "")
    print(f"Stopping Qwen Image Runner (pid {pid})...")
    try:
        req = urllib.request.Request(
            APP_URL + "/api/app/quit", method="POST",
            headers={"X-CSRF": csrf, "Content-Type": "application/json"},
            data=b"{}",
        )
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        pass  # the server may already be shutting down
    deadline = time.time() + 12
    while time.time() < deadline:
        try:
            get_json(APP_URL + "/api/meta", 1.0)
        except Exception:
            print("Stopped.")
            return 0
        time.sleep(0.5)
    if pid:
        print("Graceful stop timed out - forcing shutdown.")
        subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)
        parent = meta.get("parent_pid")
        if parent and parent not in (0, pid):
            subprocess.run(["taskkill", "/PID", str(parent), "/F"], capture_output=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
