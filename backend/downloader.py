"""Qwen Image Runner — resumable model downloads with progress reporting."""
from __future__ import annotations

import hashlib
import threading
import time
import zipfile
from pathlib import Path
from typing import Callable, Optional

import httpx

from . import config

_state_lock = threading.Lock()
_state: dict = {
    "active": False,
    "component": None,
    "done_bytes": 0,
    "total_bytes": 0,
    "error": None,
    "cancelled": False,
    "verified": {},
}
_thread: Optional[threading.Thread] = None


def manifest_components() -> list[dict]:
    manifest = config.load_manifest(config.MODELS_MANIFEST)
    return manifest.get("components", [])


def component_status() -> list[dict]:
    out = []
    for comp in manifest_components():
        path = config.ROOT / comp["path"]
        exists = path.exists()
        size = path.stat().st_size if exists else 0
        out.append({
            "id": comp["id"],
            "name": comp.get("name", comp["id"]),
            "role": comp.get("role", ""),
            "optional": bool(comp.get("optional")),
            "bytes": comp.get("bytes", 0),
            "present": exists and size == comp.get("bytes", size),
            "actual_bytes": size,
            "url": comp.get("url", ""),
            "destination": comp["path"],
        })
    return out


def missing_required() -> list[str]:
    return [c["id"] for c in component_status() if not c["present"] and not c["optional"]]


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def download_all(components: list[str] | None = None, on_progress: Optional[Callable[[dict], None]] = None) -> None:
    """Start a background download of the selected (or all missing) components."""
    global _thread
    with _state_lock:
        if _state["active"]:
            return
        _state.update(active=True, component=None, done_bytes=0, total_bytes=0, error=None, cancelled=False)
    targets = [c for c in manifest_components() if (components is None or c["id"] in components)]

    def run():
        try:
            for comp in targets:
                if _state["cancelled"]:
                    break
                dest = config.ROOT / comp["path"]
                dest.parent.mkdir(parents=True, exist_ok=True)
                expected = comp.get("bytes", 0)
                if dest.exists() and expected and dest.stat().st_size == expected:
                    continue
                _download_one(comp, dest, on_progress)
                if comp.get("sha256") and dest.exists():
                    ok = _sha256(dest) == comp["sha256"]
                    _state["verified"][comp["id"]] = ok
                    if not ok:
                        raise RuntimeError(f"checksum mismatch for {comp['id']}")
        except Exception as exc:  # noqa: BLE001
            _state["error"] = str(exc)
        finally:
            with _state_lock:
                _state["active"] = False
                _state["component"] = None
            _emit(on_progress)

    _thread = threading.Thread(target=run, daemon=True)
    _thread.start()


def cancel_download() -> None:
    _state["cancelled"] = True


def download_state() -> dict:
    with _state_lock:
        return dict(_state)


def _emit(on_progress: Optional[Callable[[dict], None]]) -> None:
    if on_progress:
        on_progress(download_state())


def _download_one(comp: dict, dest: Path, on_progress: Optional[Callable[[dict], None]]) -> None:
    url = comp["url"]
    total = comp.get("bytes", 0)
    existing = dest.stat().st_size if dest.exists() else 0
    headers = {"Range": f"bytes={existing}-"} if existing else {}
    mode = "ab" if existing else "wb"
    with _state_lock:
        _state.update(component=comp["id"], done_bytes=existing, total_bytes=total)
    _emit(on_progress)
    with httpx.stream("GET", url, headers=headers, follow_redirects=True, timeout=60) as r:
        if existing and r.status_code == 200:
            # server ignored Range: restart cleanly
            existing = 0
            mode = "wb"
        r.raise_for_status()
        done = existing
        last_emit = 0.0
        with open(dest, mode) as f:
            for chunk in r.iter_bytes(1024 * 256):
                if _state["cancelled"]:
                    raise RuntimeError("download cancelled")
                f.write(chunk)
                done += len(chunk)
                with _state_lock:
                    _state["done_bytes"] = done
                    if not _state["total_bytes"]:
                        cl = r.headers.get("content-length")
                        if cl and cl.isdigit():
                            _state["total_bytes"] = done + int(cl)
                now = time.time()
                if now - last_emit > 0.25:
                    last_emit = now
                    _emit(on_progress)
    _emit(on_progress)


# ---------------------------------------------------------------- engine builds

def engine_assets(backend: str) -> list[dict]:
    manifest = config.load_manifest(config.ENGINE_MANIFEST)
    spec = config.BACKENDS.get(backend)
    if not spec:
        return []
    available = manifest.get("assets", {})
    return [{"id": key, **available[key]} for key in spec["assets"] if key in available]


def engine_asset_status(backend: str) -> list[dict]:
    out = []
    for asset in engine_assets(backend):
        path = config.ROOT / asset["dest"]
        out.append({
            "id": asset["id"],
            "bytes": asset.get("bytes", 0),
            "downloaded": path.exists() and path.stat().st_size == asset.get("bytes"),
        })
    return out


def backend_installed(backend: str) -> bool:
    spec = config.BACKENDS.get(backend)
    return bool(spec) and (config.ROOT / spec["exe"]).exists()


def download_engine(backend: str, on_progress: Optional[Callable[[dict], None]] = None) -> None:
    """Download + verify + extract the engine build for one backend."""
    global _thread
    with _state_lock:
        if _state["active"]:
            return
        _state.update(active=True, component=None, done_bytes=0, total_bytes=0,
                      error=None, cancelled=False)
    assets = engine_assets(backend)

    def run() -> None:
        try:
            for asset in assets:
                if _state["cancelled"]:
                    break
                dest = config.ROOT / asset["dest"]
                dest.parent.mkdir(parents=True, exist_ok=True)
                if not (dest.exists() and dest.stat().st_size == asset.get("bytes")):
                    _download_one(asset, dest, on_progress)
                if asset.get("sha256") and dest.exists():
                    ok = _sha256(dest) == asset["sha256"]
                    _state["verified"][asset["id"]] = ok
                    if not ok:
                        raise RuntimeError(f"checksum mismatch for {asset['id']}")
                extract_to = config.ROOT / asset["extract_to"]
                extract_to.mkdir(parents=True, exist_ok=True)
                with zipfile.ZipFile(dest) as zf:
                    zf.extractall(extract_to)
        except Exception as exc:  # noqa: BLE001
            _state["error"] = str(exc)
        finally:
            with _state_lock:
                _state["active"] = False
                _state["component"] = None
            _emit(on_progress)

    _thread = threading.Thread(target=run, daemon=True)
    _thread.start()
