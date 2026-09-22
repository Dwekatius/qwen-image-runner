#!/usr/bin/env python
"""Launch Qwen Image Runner: reuse a running instance or start a detached one, then open the UI.

Uses only the standard library so it always works from Launch.bat.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

try:  # Windows consoles may default to cp437/cp1252
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
APP_URL = "http://127.0.0.1:7878"
META_URL = APP_URL + "/api/meta"


def meta(timeout: float = 2.0) -> dict | None:
    try:
        with urllib.request.urlopen(META_URL, timeout=timeout) as r:
            data = json.loads(r.read().decode())
        if data.get("app") == "Qwen Image Runner":
            return data
    except Exception:
        return None
    return None


def open_window(url: str) -> None:
    candidates = [
        os.environ.get("CHROME_PATH", ""),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        str(Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe"),
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            subprocess.Popen([candidate, f"--app={url}", "--window-size=1500,950"])
            return
    webbrowser.open(url)


def main() -> int:
    py = ROOT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not py.exists():
        print("Please run Install.bat first (virtual environment missing).")
        return 1

    running = meta()
    if running:
        print(f"Qwen Image Runner is already running (pid {running.get('pid')}) - opening the studio.")
        open_window(APP_URL)
        return 0

    log_dir = ROOT / "logs"
    log_dir.mkdir(exist_ok=True)
    log_file = open(log_dir / "app.log", "ab")
    creation = 0
    if os.name == "nt":
        creation = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    env = dict(os.environ)
    env["PYTHONUNBUFFERED"] = "1"
    proc = subprocess.Popen(
        [str(py), "-m", "backend.main"],
        cwd=str(ROOT), stdout=log_file, stderr=subprocess.STDOUT,
        creationflags=creation, env=env,
    )
    print(f"Starting Qwen Image Runner (pid {proc.pid})...")

    deadline = time.time() + 60
    while time.time() < deadline:
        if proc.poll() is not None:
            print("The app exited during startup. See logs\\app.log for details.")
            return 1
        if meta(1.0):
            print("Ready - opening the studio.")
            open_window(APP_URL)
            return 0
        time.sleep(1)
    print("Timed out waiting for the app to start. See logs\\app.log.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
