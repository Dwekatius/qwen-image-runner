"""Qwen Image Runner — engine supervisor.

Owns the sd-server process, parses its stdout for readiness and *real* step
progress, and exposes submit/poll/cancel for the job runner. A MockEngine is
provided for tests and GPU-less development (`QCANVAS_FAKE_ENGINE=1`).
"""
from __future__ import annotations

import asyncio
import base64
import io
import os
import re
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional

import httpx

from . import config

ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
STEP_RE = re.compile(r"\|\s*(\d+)\s*/\s*(\d+)\s*-\s*([0-9.]+)\s*(s/it|it/s)")
TILE_RE = re.compile(r"\|\s*(\d+)\s*/\s*(\d+)\s*-\s*([0-9.]+)\s*(s/it|it/s)")


class EngineError(RuntimeError):
    pass


class BaseEngine:
    state: str = "stopped"  # stopped|starting|ready|busy|failed
    last_error: str = ""
    progress: dict = {}
    started_at: Optional[float] = None

    async def ensure_ready(self, timeout: float = 180.0) -> None: ...
    async def submit(self, payload: dict) -> str: ...
    async def poll(self, engine_job: str) -> dict: ...
    async def cancel(self, engine_job: str) -> tuple[int, dict]: ...
    async def stop(self) -> None: ...
    def status(self) -> dict: ...


class RealEngine(BaseEngine):
    def __init__(self, settings: dict):
        self.settings = settings
        self.proc: Optional[subprocess.Popen] = None
        self.state = "stopped"
        self.last_error = ""
        self.progress: dict = {}
        self.started_at: Optional[float] = None
        self._ready = threading.Event()
        self._log_path = config.LOGS_DIR / "engine.log"
        self._reader: Optional[threading.Thread] = None
        self._restarts = 0
        self._lock = asyncio.Lock()

    # ------------------------------------------------------------- lifecycle
    def _engine_args(self) -> list[str]:
        eng = self.settings["engine"]
        args = [
            str(config.backend_exe(self.settings)),
            "--diffusion-model", str(config.ROOT / eng["diffusion_model"]),
            "--vae", str(config.ROOT / eng["vae"]),
            "--llm", str(config.ROOT / eng["text_encoder"]),
            "--llm_vision", str(config.ROOT / eng["vision_projector"]),
            "--listen-ip", config.ENGINE_HOST,
            "--listen-port", str(config.ENGINE_PORT),
            "--log-level", "verbose",
        ] + config.backend_args(self.settings)
        return args

    async def start(self) -> None:
        async with self._lock:
            if self.state in ("starting", "ready", "busy"):
                return
            exe = config.backend_exe(self.settings)
            if not exe.exists():
                spec = config.backend_spec(self.settings)
                self.state = "failed"
                self.last_error = (
                    f"engine binary for '{spec['label']}' is not installed. "
                    "Open Settings > Engine backend and click Install."
                )
                raise EngineError(self.last_error)
            config.ensure_dirs()
            self._log_path.write_bytes(b"")  # rotate on start
            self._ready.clear()
            self.state = "starting"
            self.progress = {}
            self.last_error = ""
            self.started_at = time.time()
            creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            self.proc = subprocess.Popen(
                self._engine_args(),
                cwd=str(config.backend_dir(self.settings)),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                creationflags=creationflags,
            )
            self._reader = threading.Thread(target=self._read_loop, daemon=True)
            self._reader.start()

    async def stop(self) -> None:
        async with self._lock:
            proc, self.proc = self.proc, None
            self.state = "stopped"
            self.progress = {}
            self._ready.clear()
        if proc and proc.poll() is None:
            try:
                proc.terminate()
                await asyncio.to_thread(proc.wait, 10)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass

    async def ensure_ready(self, timeout: float = 180.0) -> None:
        if self.state in ("ready", "busy"):
            return
        if self.state in ("stopped", "failed"):
            self._restarts = 0
            await self.start()
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.state in ("ready", "busy"):
                return
            if self.state == "failed":
                raise EngineError(self.last_error or "engine failed to start")
            await asyncio.sleep(0.25)
        raise EngineError("engine did not become ready in time")

    # ------------------------------------------------------------- output
    def _read_loop(self) -> None:
        proc = self.proc
        if not proc or not proc.stdout:
            return
        buf = b""
        with open(self._log_path, "ab") as log:
            while True:
                chunk = proc.stdout.read1(4096)
                if not chunk:
                    break
                log.write(chunk)
                log.flush()
                buf += chunk
                # progress lines are \r-separated; split on both
                while True:
                    m = re.search(rb"[\r\n]", buf)
                    if not m:
                        break
                    line, buf = buf[: m.start()], buf[m.end():]
                    self._handle_line(line.decode("utf-8", "replace"))
        if self.proc is proc:
            code = proc.poll()
            self.proc = None
            if self.state not in ("stopped",):
                self.state = "failed"
                self.last_error = f"engine exited unexpectedly (code {code})"

    def _handle_line(self, raw: str) -> None:
        line = ANSI_RE.sub("", raw).strip()
        if not line:
            return
        if "listening on" in line:
            self.state = "ready"
            self._ready.set()
            return
        m = STEP_RE.search(line)
        if m:
            step, total, rate, unit = int(m.group(1)), int(m.group(2)), float(m.group(3)), m.group(4)
            self.progress = {
                "phase": "sampling",
                "step": step, "total": total, "rate": rate, "unit": unit, "ts": time.time(),
            }
            return
        low = line.lower()
        if "decoding" in low and "latents" in low:
            self.progress = {"phase": "decoding", "ts": time.time()}
        elif "sampling completed" in low:
            self.progress = {"phase": "decoding", "ts": time.time()}

    # ------------------------------------------------------------- HTTP API
    @property
    def base(self) -> str:
        return f"http://{config.ENGINE_HOST}:{config.ENGINE_PORT}"

    async def submit(self, payload: dict) -> str:
        await self.ensure_ready()
        self.state = "busy"
        self.progress = {"phase": "queued", "ts": time.time()}
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(f"{self.base}/sdcpp/v1/img_gen", json=payload)
            r.raise_for_status()
            data = r.json()
        return data["id"]

    async def poll(self, engine_job: str) -> dict:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(f"{self.base}/sdcpp/v1/jobs/{engine_job}")
            r.raise_for_status()
            data = r.json()
        status = data.get("status")
        if status in ("completed", "failed", "cancelled"):
            if self.state == "busy":
                self.state = "ready"
        else:
            # This engine build does not print per-step progress; once it reports the job
            # is generating, stop claiming it is still queued (stdout parsing can still
            # upgrade this to phase 'sampling' with real step counts).
            if status == "generating" and self.progress.get("phase") in (None, "queued"):
                self.progress = {"phase": "rendering", "ts": time.time()}
        return data

    async def cancel(self, engine_job: str) -> tuple[int, dict]:
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.post(f"{self.base}/sdcpp/v1/jobs/{engine_job}/cancel")
            try:
                body = r.json()
            except Exception:
                body = {"raw": r.text[:300]}
            return r.status_code, body

    def status(self) -> dict:
        spec = config.backend_spec(self.settings)
        return {
            "state": self.state,
            "backend": (self.settings.get("engine", {}) or {}).get("backend", config.DEFAULT_BACKEND),
            "backend_label": spec["label"],
            "error": self.last_error,
            "progress": self.progress,
            "started_at": self.started_at,
            "fake": False,
        }


class MockEngine(BaseEngine):
    """Simulated engine: instant startup, real-looking progress, placeholder image."""

    STEP_TIME = 0.05

    def __init__(self, settings: dict):
        self.settings = settings
        self.state = "ready"
        self.jobs: dict[str, dict] = {}
        self._t0 = time.time()

    async def ensure_ready(self, timeout: float = 5.0) -> None:
        if self.state == "stopped":
            self.state = "ready"

    async def stop(self) -> None:
        self.state = "stopped"

    async def submit(self, payload: dict) -> str:
        job_id = f"mock_{int(time.time()*1000)}_{len(self.jobs)}"
        steps = int(payload.get("sample_params", {}).get("sample_steps", 40))
        self.jobs[job_id] = {
            "payload": payload, "created": time.time(), "steps": steps,
            "status": "generating", "cancelled": False,
        }
        self.state = "busy"
        return job_id

    async def poll(self, engine_job: str) -> dict:
        job = self.jobs.get(engine_job)
        if not job:
            return {"status": "failed", "error": {"message": "unknown job"}}
        elapsed = time.time() - job["created"]
        step = min(int(elapsed / self.STEP_TIME), job["steps"])
        pct = step / max(job["steps"], 1)
        self.progress = {
            "phase": "sampling" if pct < 1 else "decoding",
            "step": step, "total": job["steps"], "rate": self.STEP_TIME, "unit": "s/it",
        }
        if job["cancelled"]:
            return {"status": "cancelled", "error": {"code": "cancelled", "message": "job cancelled by client"}}
        if pct < 1:
            return {"status": "generating"}
        await asyncio.sleep(0.2)  # simulate decode
        self.state = "ready"
        return {"status": "completed", "result": {"images": [{"index": 0, "b64_json": self._placeholder(job["payload"])}]}}

    async def cancel(self, engine_job: str) -> tuple[int, dict]:
        job = self.jobs.get(engine_job)
        if not job:
            return 404, {"error": "unknown job"}
        if job["status"] == "generating" and (time.time() - job["created"]) < self.STEP_TIME * 2:
            job["cancelled"] = True
            return 200, {"status": "cancelled"}
        job["cancelled"] = True
        return 200, {"status": "cancelled"}

    def _placeholder(self, payload: dict) -> str:
        from PIL import Image, ImageDraw
        w = min(int(payload.get("width", 512)), 1024)
        h = min(int(payload.get("height", 512)), 1024)
        im = Image.new("RGBA", (w, h), (24, 28, 38, 255))
        d = ImageDraw.Draw(im)
        for i in range(0, max(w, h), 64):
            d.rectangle((i, 0, i + 32, h), fill=(32, 38, 52, 255))
        d.text((24, 24), "MOCK ENGINE", fill=(120, 200, 255, 255))
        d.text((24, 48), (payload.get("prompt") or "")[:80], fill=(200, 205, 215, 255))
        buf = io.BytesIO()
        im.save(buf, "PNG")
        return base64.b64encode(buf.getvalue()).decode()

    def status(self) -> dict:
        return {
            "state": self.state, "error": "", "progress": self.progress,
            "backend": (self.settings.get("engine", {}) or {}).get("backend", config.DEFAULT_BACKEND),
            "backend_label": config.backend_spec(self.settings)["label"],
            "started_at": self._t0, "fake": True,
        }


def make_engine(settings: dict) -> BaseEngine:
    if config.in_fake_mode():
        return MockEngine(settings)
    return RealEngine(settings)
