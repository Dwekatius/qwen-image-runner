"""Qwen Image Runner — authoritative job queue.

One worker, one in-flight engine job. Persists state transitions, streams
events to the UI, implements queued cancellation and the honest stop/reload
semantics for active inference (engine cancel -> 409 -> engine reload).
"""
from __future__ import annotations

import asyncio
import base64
import re
import time
from pathlib import Path
from typing import Optional

from . import db, storage
from .engine import BaseEngine, EngineError

TERMINAL = {"completed", "failed", "cancelled", "interrupted"}


class EventBus:
    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue] = set()

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=256)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subscribers.discard(q)

    def publish(self, event: dict) -> None:
        for q in list(self._subscribers):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                pass


class JobRunner:
    def __init__(self, engine: BaseEngine, settings: dict, bus: EventBus):
        self.engine = engine
        self.settings = settings
        self.bus = bus
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self.cancel_requests: set[str] = set()
        self.stopping: set[str] = set()
        self.active_job: Optional[str] = None
        self._task: Optional[asyncio.Task] = None

    # ------------------------------------------------------------- public API
    def start(self) -> None:
        if not self._task:
            self._task = asyncio.create_task(self._worker())

    async def submit(self, params: dict) -> str:
        job_id = db.create_job(params.get("mode", "generate"), params)
        await self.queue.put(job_id)
        self.bus.publish({"type": "job", "id": job_id, "status": "queued", "params": params})
        return job_id

    async def submit_batch(self, base_params: dict) -> list[str]:
        ids = []
        batch = int(base_params.pop("batch", 1) or 1)
        seed = base_params.get("seed")
        for i in range(max(1, min(batch, 4))):
            params = dict(base_params)
            if seed is not None and seed >= 0:
                params["seed"] = int(seed) + i
            params["batch_index"] = i
            ids.append(await self.submit(params))
        return ids

    def request_cancel(self, job_id: str) -> str:
        """Returns the action taken: 'none' | 'marked' | 'stopping'."""
        job = db.get_job(job_id)
        if not job or job["status"] in TERMINAL:
            return "none"
        if self.active_job == job_id:
            return "active"
        self.cancel_requests.add(job_id)
        return "marked"

    async def stop_active(self) -> dict:
        """Stop the in-flight engine job: cooperative cancel first, engine reload as fallback."""
        job_id = self.active_job
        engine_job = None
        if job_id:
            job = db.get_job(job_id)
            engine_job = job.get("engine_job") if job else None
        if not engine_job:
            return {"action": "idle"}
        code, body = await self.engine.cancel(engine_job)
        if code == 200:
            return {"action": "cancelled"}
        # active inference cannot be interrupted -> reload the engine (honest semantics)
        self.stopping.add(job_id)
        db.update_job(job_id, status="stopping")
        self.bus.publish({"type": "job", "id": job_id, "status": "stopping"})
        await self.engine.stop()
        await self.engine.start()
        return {"action": "reloaded", "engine_response": body}

    def queue_depth(self) -> int:
        return self.queue.qsize()

    def status(self) -> dict:
        return {
            "queue_depth": self.queue_depth(),
            "active_job": self.active_job,
            "engine": self.engine.status(),
        }

    # ---------------------------------------------------------------- chat
    def _chat_note(self, params: dict, job_id: str, text: str) -> None:
        if params.get("chat"):
            chat_id = params.get("chat_id")
            if chat_id:
                db.add_chat_message(chat_id, "assistant", text=text, job_id=job_id)
                self.bus.publish({"type": "chat"})

    # ---------------------------------------------------------------- worker
    async def _worker(self) -> None:
        while True:
            job_id = await self.queue.get()
            try:
                await self._process(job_id)
            except Exception as exc:  # noqa: BLE001
                db.update_job(job_id, status="failed", error=str(exc), finished=time.time())
                self.bus.publish({"type": "job", "id": job_id, "status": "failed", "error": str(exc)})
            finally:
                self.active_job = None
                self.queue.task_done()

    async def _process(self, job_id: str) -> None:
        job = db.get_job(job_id)
        if not job:
            return
        if job_id in self.cancel_requests:
            self.cancel_requests.discard(job_id)
            db.update_job(job_id, status="cancelled", finished=time.time())
            self.bus.publish({"type": "job", "id": job_id, "status": "cancelled"})
            self._chat_note(job.get("params") or {}, job_id, "Cancelled.")
            return

        params = job["params"]
        self.active_job = job_id
        db.update_job(job_id, status="running", started=time.time())
        self.bus.publish({"type": "job", "id": job_id, "status": "running", "params": params})

        try:
            payload = self._engine_payload(params)
            engine_job = await self.engine.submit(payload)
            db.update_job(job_id, engine_job=engine_job)
        except EngineError as exc:
            db.update_job(job_id, status="failed", error=str(exc), finished=time.time())
            self.engine.state = "failed"
            self.bus.publish({"type": "job", "id": job_id, "status": "failed", "error": str(exc)})
            self._chat_note(params, job_id, f"Generation failed: {exc}")
            return

        poll_interval = 1.0
        while True:
            if job_id in self.stopping:
                self.stopping.discard(job_id)
                db.update_job(job_id, status="interrupted", finished=time.time(),
                              error="stopped by user (engine reloaded)")
                self.bus.publish({"type": "job", "id": job_id, "status": "interrupted"})
                self._chat_note(params, job_id, "Stopped — engine reloaded.")
                return
            if job_id in self.cancel_requests:
                self.cancel_requests.discard(job_id)
                code, body = await self.engine.cancel(engine_job)
                if code == 200:
                    db.update_job(job_id, status="cancelled", finished=time.time())
                    self.bus.publish({"type": "job", "id": job_id, "status": "cancelled"})
                    self._chat_note(params, job_id, "Cancelled.")
                    return
                # cannot interrupt -> reload engine, mark interrupted
                await self.engine.stop()
                await self.engine.start()
                db.update_job(job_id, status="interrupted", finished=time.time(),
                              error="stopped by user (engine reloaded)")
                self.bus.publish({"type": "job", "id": job_id, "status": "interrupted"})
                self._chat_note(params, job_id, "Stopped — engine reloaded.")
                return
            try:
                result = await self.engine.poll(engine_job)
            except Exception as exc:  # network hiccup / engine died
                if job_id in self.stopping:
                    self.stopping.discard(job_id)
                    db.update_job(job_id, status="interrupted", finished=time.time(),
                                  error="stopped by user (engine reloaded)")
                    self.bus.publish({"type": "job", "id": job_id, "status": "interrupted"})
                    self._chat_note(params, job_id, "Stopped — engine reloaded.")
                    return
                db.update_job(job_id, status="failed", error=f"engine poll failed: {exc}", finished=time.time())
                self.bus.publish({"type": "job", "id": job_id, "status": "failed", "error": str(exc)})
                self._chat_note(params, job_id, f"Generation failed: {exc}")
                return

            status = result.get("status", "unknown")
            progress = dict(self.engine.status().get("progress") or {})
            progress["elapsed"] = time.time() - (job.get("started") or time.time())
            if status in ("generating", "queued", "running"):
                db.update_job(job_id, progress=progress)
                self.bus.publish({"type": "job", "id": job_id, "status": "running", "progress": progress})
                await asyncio.sleep(poll_interval)
                continue

            if status == "completed":
                self.stopping.discard(job_id)
                db.update_job(job_id, status="saving", progress={**progress, "phase": "saving"})
                self.bus.publish({"type": "job", "id": job_id, "status": "saving"})
                await self._save_result(job_id, params, result)
                db.update_job(job_id, status="completed", finished=time.time(), progress={})
                self.bus.publish({"type": "job", "id": job_id, "status": "completed"})
                return

            if status == "cancelled":
                db.update_job(job_id, status="cancelled", finished=time.time())
                self.bus.publish({"type": "job", "id": job_id, "status": "cancelled"})
                self._chat_note(params, job_id, "Cancelled.")
                return

            error = result.get("error") or {"message": status}
            db.update_job(job_id, status="failed", error=error, finished=time.time())
            self.bus.publish({"type": "job", "id": job_id, "status": "failed", "error": error})
            message = error.get("message") if isinstance(error, dict) else str(error)
            self._chat_note(params, job_id, f"Generation failed: {message}")
            return

    async def _save_result(self, job_id: str, params: dict, result: dict) -> None:
        images = (result.get("result") or {}).get("images") or []
        for entry in images:
            raw = base64.b64decode(entry["b64_json"])
            path = storage.save_output(raw, params.get("mode", "generate"),
                                       chat_id=params.get("chat_id"))
            meta = storage.image_meta(path)
            thumb = storage.make_thumbnail(path)
            transparent = storage.is_meaningfully_transparent(path)
            seed_value = params.get("seed")
            if seed_value == -1 and meta.get("png_parameters"):
                m = re.search(r"Seed:\s*(\d+)", meta["png_parameters"])
                if m:
                    seed_value = int(m.group(1))
            image_id = db.add_image(
                job_id=job_id,
                path=storage.store_path(path),
                thumb=storage.store_path(thumb) if thumb else None,
                width=meta.get("width"), height=meta.get("height"), mode=meta.get("mode"),
                seed=seed_value, prompt=params.get("prompt"), negative=params.get("negative"),
                params={**params, "transparent_output": transparent, "png_parameters": meta.get("png_parameters")},
            )
            self.bus.publish({"type": "image", "id": image_id, "job_id": job_id})
            if params.get("chat"):
                chat_id = params.get("chat_id")
                if chat_id:
                    db.add_chat_message(chat_id, "assistant", image_id=image_id, job_id=job_id)
                    self.bus.publish({"type": "chat"})

    def _engine_payload(self, params: dict) -> dict:
        prompt = params.get("prompt") or ""
        if params.get("transparent"):
            prompt = ("This is an RGBA image with transparency. " + prompt +
                      " The image has alpha channel and the background is transparent.")
        payload: dict = {
            "prompt": prompt,
            "negative_prompt": params.get("negative") or "",
            "width": int(params.get("width", 1024)),
            "height": int(params.get("height", 1024)),
            "seed": int(params.get("seed", -1)),
            "batch_count": 1,
            "embed_image_metadata": True,
            "output_format": "png",
            "sample_params": {
                "scheduler": "discrete",
                "sample_method": params.get("sampler", "euler"),
                "sample_steps": int(params.get("steps", 40)),
                "guidance": {"txt_cfg": float(params.get("cfg", 6.0))},
            },
        }
        refs = params.get("refs") or []
        if refs:
            data_urls = []
            for ref in refs:
                path = storage.resolve_path(ref)
                b64 = base64.b64encode(path.read_bytes()).decode()
                data_urls.append(f"data:image/png;base64,{b64}")
            payload["ref_images"] = data_urls
        mask = params.get("mask")
        if mask:
            path = storage.resolve_path(mask)
            b64 = base64.b64encode(path.read_bytes()).decode()
            payload["mask_image"] = f"data:image/png;base64,{b64}"
        return payload


def config_root() -> Path:
    from . import config
    return config.ROOT
