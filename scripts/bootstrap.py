#!/usr/bin/env python
"""Qwen Image Runner bootstrap: venv + dependencies + pinned engine download.

Runs with the *system* Python (stdlib only) so it works before the venv exists.
Model weights are NOT downloaded here — the first-run wizard in the UI does that.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENV = ROOT / ".venv"
APP_DISPLAY = "Qwen Image Runner"

try:  # Windows consoles may default to cp1252
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def msg(text: str) -> None:
    print(f"[bootstrap] {text}", flush=True)


def venv_python() -> Path:
    return VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def run(cmd: list, **kw) -> None:
    msg("run: " + " ".join(str(c) for c in cmd))
    subprocess.check_call([str(c) for c in cmd], **kw)


def setup_venv() -> None:
    if not venv_python().exists():
        msg("creating virtual environment (.venv)")
        run([sys.executable, "-m", "venv", str(VENV)])
    run([venv_python(), "-m", "pip", "install", "--upgrade", "pip", "-q"])
    run([venv_python(), "-m", "pip", "install", "-e", str(ROOT), "-q"])
    msg("dependencies installed")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def download(url: str, dest: Path, expected_bytes: int | None = None, expected_sha: str | None = None) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    existing = dest.stat().st_size if dest.exists() else 0
    if expected_bytes and existing == expected_bytes:
        msg(f"already present: {dest.name}")
        return
    headers = {"Range": f"bytes={existing}-"} if existing else {}
    req = urllib.request.Request(url, headers=headers)
    msg(f"downloading {dest.name} ({existing} bytes already)")
    with urllib.request.urlopen(req) as r:
        resume = r.status == 206
        mode = "ab" if resume else "wb"
        done = existing if resume else 0
        total = (int(r.headers.get("Content-Length", 0)) + (existing if resume else 0))
        with open(dest, mode) as f:
            while True:
                chunk = r.read(1024 * 256)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if total:
                    pct = done * 100 / total
                    print(f"\r  {dest.name}: {pct:5.1f}%", end="", flush=True)
    print()
    if expected_bytes and dest.stat().st_size != expected_bytes:
        raise RuntimeError(f"size mismatch for {dest}: {dest.stat().st_size} != {expected_bytes}")
    if expected_sha:
        msg("verifying checksum…")
        actual = sha256(dest)
        if actual != expected_sha:
            raise RuntimeError(f"checksum mismatch for {dest.name}: {actual}")


def engine_ready() -> bool:
    manifest = json.loads((ROOT / "engine.json").read_text(encoding="utf-8"))
    runtime = ROOT / manifest["runtime"]["sd_server"]
    return runtime.exists()


def setup_engine() -> None:
    sys.path.insert(0, str(ROOT))
    from backend import config as cfg  # stdlib-only module, safe before deps

    manifest = json.loads((ROOT / "engine.json").read_text(encoding="utf-8"))
    backend = os.environ.get("QIR_BACKEND", cfg.DEFAULT_BACKEND)
    spec = cfg.BACKENDS.get(backend) or cfg.BACKENDS[cfg.DEFAULT_BACKEND]
    runtime = ROOT / spec["exe"]
    msg(f"engine backend: {backend} ({spec['label']})")
    if runtime.exists():
        msg("engine already installed")
        return
    for key in spec["assets"]:
        asset = manifest["assets"][key]
        dest = ROOT / asset["dest"]
        if not dest.exists() or dest.stat().st_size != asset.get("bytes"):
            download(asset["url"], dest, asset.get("bytes"), asset.get("sha256"))
        extract_to = ROOT / asset["extract_to"]
        extract_to.mkdir(parents=True, exist_ok=True)
        msg(f"extracting {dest.name} -> {asset['extract_to']}")
        with zipfile.ZipFile(dest) as zf:
            zf.extractall(extract_to)
    if not runtime.exists():
        raise RuntimeError(f"engine binary missing after extraction: {runtime}")
    msg(f"engine ready: {runtime.relative_to(ROOT)}")


def make_shortcut() -> None:
    if os.name != "nt":
        return
    ps1 = ROOT / "scripts" / "make_shortcut.ps1"
    if not ps1.exists():
        return
    try:
        subprocess.check_call(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ps1)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        msg("desktop shortcut created")
    except Exception:
        msg("(desktop shortcut skipped)")


def main() -> int:
    msg(f"{APP_DISPLAY} bootstrap - root {ROOT}")
    if sys.version_info < (3, 11):
        msg("Python 3.11+ is required.")
        return 1
    setup_venv()
    setup_engine()
    make_shortcut()
    msg("")
    msg(f"Install complete. Start the app with Launch.bat")
    msg("Model weights download on first run inside the app (Models panel).")
    msg("Backends: NVIDIA CUDA (default), Vulkan (AMD/Intel), CPU - switch or install them in Settings.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
