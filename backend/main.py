"""Qwen Image Runner — application entry point (FastAPI + private local API)."""
from __future__ import annotations

import asyncio
import json
import os
import re
import secrets
import subprocess
import sys
import time
from pathlib import Path

import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import assistant, config, db, downloader, saveas, storage
from .engine import EngineError, make_engine
from .jobs import EventBus, JobRunner

CSRF_TOKEN = ""
START_TIME = time.time()
SHUTDOWN = asyncio.Event()

# messages that clearly ask for a brand-new image (otherwise, follow-ups edit the last image)
GENERATE_RE = re.compile(
    r"\b(generate|create|draw|imagine|render|new image|new picture|fresh image|another image)\b", re.I
)

app = FastAPI(title=config.APP_NAME, version=config.APP_VERSION, docs_url=None, redoc_url=None)

settings = config.load_settings()


def _load_or_create_csrf() -> str:
    """Keep the CSRF token stable across restarts so open windows don't break."""
    stored = settings.get("csrf_token")
    if isinstance(stored, str) and len(stored) >= 16:
        return stored
    token = secrets.token_hex(16)
    settings["csrf_token"] = token
    config.save_settings(settings)
    return token


CSRF_TOKEN = _load_or_create_csrf()

bus = EventBus()
engine = make_engine(settings)
runner = JobRunner(engine, settings, bus)

_gpu_cache: dict = {"ts": 0.0, "data": {}}
_server_ref: dict = {}


# ------------------------------------------------------------------ security
ALLOWED_HOSTS = {f"127.0.0.1:{config.APP_PORT}", f"localhost:{config.APP_PORT}", "testserver"}


@app.middleware("http")
async def local_protection(request: Request, call_next):
    host = request.headers.get("host", "")
    if host not in ALLOWED_HOSTS:
        return JSONResponse({"error": f"forbidden host: {host}"}, status_code=403)
    origin = request.headers.get("origin")
    if origin and origin not in {f"http://{h}" for h in ALLOWED_HOSTS}:
        return JSONResponse({"error": "forbidden origin"}, status_code=403)
    if request.method in ("POST", "PUT", "DELETE", "PATCH") and request.url.path.startswith("/api/"):
        if request.headers.get("x-csrf", "") != CSRF_TOKEN:
            return JSONResponse({"error": "missing or invalid CSRF token"}, status_code=403)
    return await call_next(request)


# ------------------------------------------------------------------ lifecycle
@app.on_event("startup")
async def on_startup() -> None:
    config.ensure_dirs()
    interrupted = db.reconcile_on_start()
    if interrupted:
        bus.publish({"type": "notice", "text": f"{interrupted} unfinished job(s) marked interrupted after restart"})
    runner.start()
    if settings.get("engine", {}).get("autostart", True):
        async def warm() -> None:
            try:
                await engine.ensure_ready()
                bus.publish({"type": "engine", **engine.status()})
            except EngineError as exc:
                bus.publish({"type": "engine", **engine.status(), "error": str(exc)})
        asyncio.create_task(warm())


@app.on_event("shutdown")
async def on_shutdown() -> None:
    await engine.stop()


# ------------------------------------------------------------------ meta / system
@app.get("/api/meta")
async def meta() -> dict:
    return {
        "app": config.APP_NAME,
        "version": config.APP_VERSION,
        "license": config.SPDX_LICENSE,
        "pid": os.getpid(),
        "parent_pid": os.getppid(),
        "csrf": CSRF_TOKEN,
        "uptime": time.time() - START_TIME,
        "engine": engine.status(),
        "queue": runner.status(),
        "license_accepted": bool(settings.get("license_accepted")),
        "settings": {
            "defaults": settings.get("defaults", {}),
            "engine_autostart": bool(settings.get("engine", {}).get("autostart", True)),
        },
        "paths": {
            "engine": str(config.backend_exe(settings)),
            "models": str(config.MODELS_DIR),
            "outputs": str(config.OUTPUTS_DIR),
            "inputs": str(config.INPUTS_DIR),
            "database": str(config.DB_PATH),
        },
    }


@app.get("/api/system")
async def system() -> dict:
    now = time.time()
    if now - _gpu_cache["ts"] > 2:
        data: dict = {"gpu": None}
        try:
            out = subprocess.run(
                ["nvidia-smi", "--query-gpu=memory.used,memory.free,utilization.gpu",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=5,
            )
            if out.returncode == 0:
                used, free, util = [x.strip() for x in out.stdout.strip().split(",")[:3]]
                data["gpu"] = {"used_mib": int(used), "free_mib": int(free), "util": int(util)}
        except Exception:
            pass
        _gpu_cache.update(ts=now, data=data)
    return {
        "gpu": _gpu_cache["data"].get("gpu"),
        "engine": engine.status(),
        "queue": runner.status(),
        "queue_depth": runner.queue_depth(),
    }


@app.get("/api/samplers")
async def samplers() -> dict:
    fallback = ["euler", "euler_a", "heun", "dpmpp_2m"]
    if engine.status().get("fake"):
        return {"samplers": fallback}
    try:
        import httpx
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(f"http://{config.ENGINE_HOST}:{config.ENGINE_PORT}/sdapi/v1/samplers")
            data = r.json()
        names = [s.get("name") for s in data if s.get("name")]
        return {"samplers": names or fallback}
    except Exception:
        return {"samplers": fallback}


# ------------------------------------------------------------------ models
@app.get("/api/models")
async def models() -> dict:
    statuses = downloader.component_status()
    return {
        "components": statuses,
        "missing_required": downloader.missing_required(),
        "download": downloader.download_state(),
        "license_accepted": bool(settings.get("license_accepted")),
        "license": {
            "app": config.SPDX_LICENSE,
            "app_url": "https://www.gnu.org/licenses/gpl-3.0.html",
            "model": "Qwen Research License (research/evaluation; separate permission for commercial use)",
            "model_url": "https://huggingface.co/Qwen/Qwen-Image-2.1/raw/main/LICENSE",
            "unofficial": "Unofficial project — not affiliated with, endorsed by, or connected to Alibaba/Qwen.",
        },
    }


@app.post("/api/models/license")
async def accept_license(body: dict) -> dict:
    settings["license_accepted"] = bool(body.get("accepted"))
    config.save_settings(settings)
    return {"ok": True, "accepted": settings["license_accepted"]}


@app.post("/api/models/download")
async def start_download(body: dict | None = None) -> dict:
    if not settings.get("license_accepted"):
        raise HTTPException(status_code=400, detail="model license must be accepted first")
    components = (body or {}).get("components")
    downloader.download_all(components, on_progress=lambda s: bus.publish({"type": "download", **s}))
    return {"ok": True, "download": downloader.download_state()}


@app.post("/api/models/download/cancel")
async def cancel_download() -> dict:
    downloader.cancel_download()
    return {"ok": True}


@app.get("/api/models/download")
async def download_progress() -> dict:
    return downloader.download_state()


# ------------------------------------------------------------------ engine control
@app.post("/api/engine/start")
async def engine_start() -> dict:
    try:
        await engine.ensure_ready()
    except EngineError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return engine.status()


@app.post("/api/engine/stop")
async def engine_stop() -> dict:
    await engine.stop()
    return engine.status()


@app.post("/api/engine/restart")
async def engine_restart() -> dict:
    await engine.stop()
    try:
        await engine.ensure_ready()
    except EngineError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return engine.status()


@app.get("/api/engine/backends")
async def engine_backends() -> dict:
    current = (settings.get("engine", {}) or {}).get("backend", config.DEFAULT_BACKEND)
    out = []
    for key, spec in config.BACKENDS.items():
        out.append({
            "id": key,
            "label": spec["label"],
            "detail": spec["detail"],
            "speed": spec.get("speed", ""),
            "installed": downloader.backend_installed(key),
            "assets": downloader.engine_asset_status(key),
            "current": key == current,
        })
    return {"backends": out, "current": current, "download": downloader.download_state()}


@app.post("/api/engine/backend")
async def engine_set_backend(body: dict) -> dict:
    backend = (body or {}).get("backend")
    if backend not in config.BACKENDS:
        raise HTTPException(status_code=400, detail="unknown backend")
    settings["engine"]["backend"] = backend
    config.save_settings(settings)
    # keep the supervisor and job runner on the current settings object
    engine.settings = settings
    runner.settings = settings
    await engine.stop()
    bus.publish({"type": "engine", **engine.status()})

    if settings.get("engine", {}).get("autostart", True):
        async def warm() -> None:
            try:
                await engine.ensure_ready()
                bus.publish({"type": "engine", **engine.status()})
            except EngineError as exc:
                bus.publish({"type": "engine", **engine.status(), "error": str(exc)})
        asyncio.create_task(warm())
    return {"ok": True, "backend": backend, "installed": downloader.backend_installed(backend)}


@app.post("/api/engine/install")
async def engine_install(body: dict) -> dict:
    backend = (body or {}).get("backend")
    if backend not in config.BACKENDS:
        raise HTTPException(status_code=400, detail="unknown backend")
    downloader.download_engine(backend, on_progress=lambda s: bus.publish({"type": "download", **s}))
    return {"ok": True, "download": downloader.download_state()}


# ------------------------------------------------------------------ generation
@app.post("/api/generate")
async def generate(body: dict) -> dict:
    prompt = (body.get("prompt") or "").strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt is required")
    params = _normalize_params(body, mode="generate")
    job_ids = await runner.submit_batch(params)
    return {"jobs": job_ids}


@app.post("/api/edit")
async def edit(
    instruction: str = Form(...),
    width: int = Form(1024),
    height: int = Form(1024),
    steps: int = Form(40),
    cfg: float = Form(6.0),
    sampler: str = Form("euler"),
    seed: int = Form(-1),
    transparent: bool = Form(False),
    ref_asset_ids: str = Form(""),
    files: list[UploadFile] = File(default=[]),
) -> dict:
    instruction = instruction.strip()
    if not instruction:
        raise HTTPException(status_code=400, detail="instruction is required")
    refs: list[str] = []
    for upload in files or []:
        data = await upload.read()
        if not data:
            continue
        if len(data) > 32 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="reference image too large (max 32 MB)")
        path = storage.save_input(data)
        refs.append(storage.store_path(path))
    for image_id in [x for x in ref_asset_ids.split(",") if x]:
        img = db.get_image(image_id)
        if img:
            refs.append(img["path"])
    if not refs:
        raise HTTPException(status_code=400, detail="at least one reference image is required")
    if len(refs) > 10:
        raise HTTPException(status_code=400, detail="at most 10 reference images are supported")
    params = _normalize_params(
        {"prompt": instruction, "width": width, "height": height, "steps": steps,
         "cfg": cfg, "sampler": sampler, "seed": seed, "transparent": transparent},
        mode="edit",
    )
    params["refs"] = refs
    job_ids = await runner.submit_batch(params)
    return {"jobs": job_ids}


def _normalize_params(body: dict, mode: str) -> dict:
    width = int(body.get("width", 1024))
    height = int(body.get("height", 1024))
    width = max(256, min(4096, (width // 32) * 32))
    height = max(256, min(4096, (height // 32) * 32))
    return {
        "mode": mode,
        "prompt": body.get("prompt", ""),
        "negative": body.get("negative", ""),
        "width": width,
        "height": height,
        "steps": max(4, min(80, int(body.get("steps", 40)))),
        "cfg": max(0.0, min(20.0, float(body.get("cfg", 6.0)))),
        "sampler": body.get("sampler", "euler"),
        "seed": int(body.get("seed", -1)),
        "batch": int(body.get("batch", 1)),
        "transparent": bool(body.get("transparent", False)),
    }


# ------------------------------------------------------------------ settings profiles
PROFILE_SIZE_RE = re.compile(r"^(\d{3,4})x(\d{3,4})$")


def _clamp_dim(value: int) -> int:
    return max(256, min(4096, (int(value) // 32) * 32))


def _sanitize_size(value, fallback: str = "1024x1024") -> str:
    match = PROFILE_SIZE_RE.match(str(value or "").strip().lower())
    if not match:
        return fallback
    return f"{_clamp_dim(int(match.group(1)))}x{_clamp_dim(int(match.group(2)))}"


def _clamp_int(value, low: int, high: int, fallback: int) -> int:
    try:
        return max(low, min(high, int(float(value))))
    except (TypeError, ValueError):
        return fallback


def _clamp_float(value, low: float, high: float, fallback: float) -> float:
    try:
        return max(low, min(high, float(value)))
    except (TypeError, ValueError):
        return fallback


def _sanitize_profile_defaults(raw, base: dict | None = None) -> dict:
    """Clamp a profile's defaults into the ranges the panel supports."""
    raw = raw if isinstance(raw, dict) else {}
    base = base if isinstance(base, dict) else {}
    fallback = {
        "size": _sanitize_size(base.get("size"), "1024x1024"),
        "steps": _clamp_int(base.get("steps"), 10, 60, 40),
        "cfg": _clamp_float(base.get("cfg"), 1.0, 10.0, 6.0),
        "sampler": str(base.get("sampler") or "").strip()[:40] or "euler",
        "batch": _clamp_int(base.get("batch"), 1, 4, 1),
        "transparent": bool(base.get("transparent", False)),
    }
    out = dict(fallback)
    if raw.get("size") is not None:
        out["size"] = _sanitize_size(raw.get("size"), fallback["size"])
    if raw.get("steps") is not None:
        out["steps"] = _clamp_int(raw.get("steps"), 10, 60, fallback["steps"])
    if raw.get("cfg") is not None:
        out["cfg"] = _clamp_float(raw.get("cfg"), 1.0, 10.0, fallback["cfg"])
    if raw.get("sampler") is not None:
        out["sampler"] = str(raw.get("sampler")).strip()[:40] or fallback["sampler"]
    if raw.get("batch") is not None:
        out["batch"] = _clamp_int(raw.get("batch"), 1, 4, fallback["batch"])
    if raw.get("transparent") is not None:
        out["transparent"] = bool(raw.get("transparent"))
    return out


def _profiles_section() -> dict:
    section = settings.setdefault("profiles", {})
    if not isinstance(section, dict):
        section = {}
        settings["profiles"] = section
    if not isinstance(section.get("items"), list):
        section["items"] = []
    section.setdefault("active", "auto")
    return section


def _find_profile(pid: str) -> dict | None:
    for item in _profiles_section().get("items", []):
        if isinstance(item, dict) and item.get("id") == pid:
            return item
    return None


def _profiles_payload() -> dict:
    section = _profiles_section()
    profiles = []
    for item in section.get("items", []):
        if not isinstance(item, dict):
            continue
        profiles.append({
            "id": str(item.get("id") or ""),
            "name": str(item.get("name") or ""),
            "defaults": dict(item.get("defaults") or {}),
        })
    return {
        "active": section.get("active") or "auto",
        "profiles": profiles,
        "assistant_ready": assistant.config_ok(settings),
        "effective": dict(settings.get("defaults") or {}),
    }


def _apply_assistant_settings(params: dict, raw: dict) -> dict:
    """Merge the assistant's requested settings into normalized generation params."""
    applied: dict = {}
    size = raw.get("size")
    if size:
        canonical = _sanitize_size(size, "")
        if canonical:
            width, height = (int(value) for value in canonical.split("x"))
            params["width"], params["height"] = width, height
            applied["size"] = canonical
    if raw.get("steps") is not None:
        params["steps"] = _clamp_int(raw.get("steps"), 10, 60, params.get("steps", 40))
        applied["steps"] = params["steps"]
    if raw.get("cfg") is not None:
        params["cfg"] = _clamp_float(raw.get("cfg"), 1.0, 10.0, params.get("cfg", 6.0))
        applied["cfg"] = params["cfg"]
    if isinstance(raw.get("transparent"), bool):
        params["transparent"] = raw["transparent"]
        applied["transparent"] = raw["transparent"]
    return applied


@app.get("/api/profiles")
async def profiles_get() -> dict:
    return _profiles_payload()


@app.post("/api/profiles")
async def profiles_create(body: dict) -> dict:
    name = str((body or {}).get("name") or "").strip()
    if not 1 <= len(name) <= 40:
        raise HTTPException(status_code=400, detail="profile name must be 1-40 characters")
    section = _profiles_section()
    item = {
        "id": "p_" + secrets.token_hex(4),
        "name": name,
        "defaults": _sanitize_profile_defaults((body or {}).get("defaults"), settings.get("defaults")),
    }
    section["items"].append(item)
    section["active"] = item["id"]
    settings["defaults"] = dict(item["defaults"])
    config.save_settings(settings)
    bus.publish({"type": "profiles", "active": item["id"]})
    return _profiles_payload()


@app.put("/api/profiles/{pid}")
async def profiles_update(pid: str, body: dict) -> dict:
    item = _find_profile(pid)
    if item is None:
        raise HTTPException(status_code=404, detail="unknown profile")
    if "name" in (body or {}):
        name = str(body.get("name") or "").strip()
        if not 1 <= len(name) <= 40:
            raise HTTPException(status_code=400, detail="profile name must be 1-40 characters")
        item["name"] = name
    if isinstance((body or {}).get("defaults"), dict):
        item["defaults"] = _sanitize_profile_defaults(body["defaults"], item.get("defaults"))
    if _profiles_section().get("active") == pid:
        settings["defaults"] = dict(item["defaults"])
    config.save_settings(settings)
    bus.publish({"type": "profiles", "active": _profiles_section().get("active")})
    return _profiles_payload()


@app.delete("/api/profiles/{pid}")
async def profiles_delete(pid: str) -> dict:
    section = _profiles_section()
    before = len(section["items"])
    section["items"] = [item for item in section["items"]
                         if not (isinstance(item, dict) and item.get("id") == pid)]
    if len(section["items"]) == before:
        raise HTTPException(status_code=404, detail="unknown profile")
    if section.get("active") == pid:
        # Deleting the active profile falls back to Auto and the app baseline,
        # exactly like selecting Auto in the panel.
        section["active"] = "auto"
        settings["defaults"] = json.loads(json.dumps(config.DEFAULT_SETTINGS["defaults"]))
    config.save_settings(settings)
    bus.publish({"type": "profiles", "active": section.get("active")})
    return _profiles_payload()


@app.post("/api/profiles/active")
async def profiles_set_active(body: dict) -> dict:
    pid = str((body or {}).get("id") or "").strip()
    section = _profiles_section()
    if pid == "auto":
        # Auto is the app baseline: drop any profile/manual tweaks
        section["active"] = "auto"
        settings["defaults"] = json.loads(json.dumps(config.DEFAULT_SETTINGS["defaults"]))
    elif pid == "manual":
        section["active"] = "manual"
    else:
        item = _find_profile(pid)
        if item is None:
            raise HTTPException(status_code=404, detail="unknown profile")
        item["defaults"] = _sanitize_profile_defaults(item.get("defaults"), settings.get("defaults"))
        section["active"] = pid
        settings["defaults"] = dict(item["defaults"])
    config.save_settings(settings)
    bus.publish({"type": "profiles", "active": pid})
    return _profiles_payload()


# ------------------------------------------------------------------ chats
@app.get("/api/chats")
async def chats_list() -> dict:
    return {"chats": db.list_chats()}


@app.post("/api/chats")
async def chats_create(body: dict | None = None) -> dict:
    chat = db.create_chat((body or {}).get("title"))
    bus.publish({"type": "chat"})
    return {"chat": chat}


@app.delete("/api/chats/{chat_id}")
async def chats_delete(chat_id: str, delete_images: bool = True) -> dict:
    if not db.get_chat(chat_id):
        raise HTTPException(status_code=404, detail="unknown chat")
    images_deleted = 0
    images_kept = 0
    if delete_images:
        chat_dir = (config.OUTPUTS_DIR / "chats" / chat_id).resolve()
        thumbs_dir = Path(config.THUMBS_DIR).resolve()
        for image_id in db.chat_image_ids(chat_id):
            img = db.get_image(image_id)
            if not img:
                continue
            path = storage.resolve_path(img["path"])
            try:
                inside_chat = path.resolve().is_relative_to(chat_dir)
            except OSError:
                inside_chat = False
            if not inside_chat:
                # the file lives outside this chat's folder (e.g. saved elsewhere): keep it
                images_kept += 1
                continue
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
            if img.get("thumb"):
                thumb = storage.resolve_path(img["thumb"])
                try:
                    if thumb.resolve().is_relative_to(thumbs_dir):
                        thumb.unlink(missing_ok=True)
                except OSError:
                    pass
            db.delete_image(image_id)
            images_deleted += 1
    else:
        images_kept = len(db.chat_image_ids(chat_id))
    deleted = db.delete_chat(chat_id)
    bus.publish({"type": "chat"})
    return {"ok": True, "deleted": deleted, "images_deleted": images_deleted,
            "images_kept": images_kept}


@app.get("/api/chat")
async def chat_messages(chat_id: str | None = None, limit: int = 500) -> dict:
    chat = (db.get_chat(chat_id) if chat_id else None) or db.latest_chat() or db.create_chat()
    return {"chat": chat, "messages": db.list_chat(chat["id"], limit=min(limit, 1000))}


@app.post("/api/chat/submit")
async def chat_submit(body: dict) -> dict:
    text = (body.get("text") or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="message is required")
    chat = db.get_chat(body.get("chat_id") or "") or db.latest_chat() or db.create_chat()
    requested = body.get("mode") or "auto"
    auto_settings = bool(body.get("auto_settings"))
    assistant_ok = assistant.config_ok(settings)
    last_image = db.last_chat_image(chat["id"])

    # optional prompt assistant: it writes the image prompt, or answers a plain question
    assistant_meta: dict = {}
    assistant_error = None
    assistant_settings_raw: dict = {}
    if assistant_ok:
        try:
            history = db.list_chat(chat["id"], limit=20)
            current = settings.get("defaults") if auto_settings else None
            result = await assistant.run(settings, history, text, bool(last_image), current=current)
            assistant_meta = {
                "assistant_action": result.get("action") or "",
                "assistant_prompt": result.get("prompt") or "",
            }
            if result.get("reply"):
                assistant_meta["assistant_reply"] = result["reply"][:400]
            if isinstance(result.get("settings"), dict):
                assistant_settings_raw = result["settings"]
            if result["action"] == "chat":
                db.set_chat_title_if_new(chat["id"], text)
                db.add_chat_message(chat["id"], "user", text=text, meta=assistant_meta)
                db.add_chat_message(chat["id"], "assistant", text=result.get("reply") or "...")
                bus.publish({"type": "chat"})
                return {"mode": "chat", "chat_id": chat["id"], "reply": result.get("reply"),
                        "assistant_settings": None}
            if result["action"] in ("generate", "edit"):
                requested = result["action"]
        except Exception as exc:  # never block image generation on the assistant
            assistant_error = str(exc)[:200]

    if requested == "auto":
        mode = "generate" if (not last_image or GENERATE_RE.search(text)) else "edit"
    else:
        mode = requested
    if mode == "edit" and not last_image:
        mode = "generate"

    params = _normalize_params(body.get("params") or {}, mode=mode)
    # the assistant may only touch settings when the user is on the Auto profile
    if auto_settings and assistant_ok and assistant_settings_raw:
        applied = _apply_assistant_settings(params, assistant_settings_raw)
        if applied:
            assistant_meta["assistant_settings"] = applied
    params["prompt"] = (assistant_meta.get("assistant_prompt") or "").strip() or text
    params["batch"] = 1
    params["chat"] = True
    params["chat_id"] = chat["id"]
    if mode == "edit":
        params["refs"] = [last_image["path"]]
        params["ref_image_id"] = last_image["id"]

    if assistant_error and not assistant_meta:
        assistant_meta = {"assistant_error": assistant_error}

    db.set_chat_title_if_new(chat["id"], text)
    db.add_chat_message(chat["id"], "user", text=text, meta=assistant_meta or None)
    bus.publish({"type": "chat"})
    job_ids = await runner.submit_batch(params)
    return {
        "job": job_ids[0],
        "mode": mode,
        "chat_id": chat["id"],
        "ref_image_id": last_image["id"] if mode == "edit" else None,
        "assistant_prompt": assistant_meta.get("assistant_prompt") or None,
        "assistant_error": assistant_error,
        "assistant_settings": assistant_meta.get("assistant_settings"),
    }


@app.post("/api/chat/clear")
async def chat_clear(body: dict | None = None) -> dict:
    removed = db.clear_chat((body or {}).get("chat_id"))
    bus.publish({"type": "chat"})
    return {"ok": True, "removed": removed}


# ------------------------------------------------------------------ save as
@app.post("/api/images/{image_id}/save_as")
async def image_save_as(image_id: str) -> dict:
    img = db.get_image(image_id)
    if not img:
        raise HTTPException(status_code=404, detail="unknown image")
    src = storage.resolve_path(img["path"])
    if not src.exists():
        raise HTTPException(status_code=410, detail="image file missing")
    name = saveas.suggested_name(img.get("prompt"), img.get("seed"), src.suffix or ".png")

    if config.in_fake_mode():
        dest = saveas.export_folder() / name
        await asyncio.to_thread(saveas.save_image, src, dest)
        return {"saved": True, "path": str(dest), "test_mode": True}

    chosen = await asyncio.to_thread(saveas.pick_save_path, name, "Save image — Qwen Image Runner")
    if not chosen:
        return {"saved": False, "reason": "cancelled"}
    dest = await asyncio.to_thread(saveas.save_image, src, Path(chosen))
    return {"saved": True, "path": str(dest)}


# ------------------------------------------------------------------ jobs
@app.get("/api/jobs")
async def jobs(limit: int = 30) -> dict:
    return {"jobs": db.list_jobs(limit=min(limit, 200))}


@app.get("/api/jobs/{job_id}")
async def job_detail(job_id: str) -> dict:
    job = db.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="unknown job")
    return job


@app.post("/api/jobs/{job_id}/cancel")
async def cancel_job(job_id: str) -> dict:
    action = runner.request_cancel(job_id)
    if action == "active":
        result = await runner.stop_active()
        return {"ok": True, "action": result.get("action", "stopping")}
    return {"ok": True, "action": action}


@app.post("/api/queue/stop")
async def stop_queue() -> dict:
    result = await runner.stop_active()
    return {"ok": True, **result}


# ------------------------------------------------------------------ events (SSE)
@app.get("/api/events")
async def events(request: Request) -> StreamingResponse:
    async def stream():
        q = bus.subscribe()
        try:
            yield f"data: {json.dumps({'type': 'hello'})}\n\n"
            while not SHUTDOWN.is_set():
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(q.get(), timeout=2.0)
                    yield f"data: {json.dumps(event)}\n\n"
                except asyncio.TimeoutError:
                    yield f"data: {json.dumps({'type': 'tick', 'engine': engine.status(), 'queue_depth': runner.queue_depth()})}\n\n"
        finally:
            bus.unsubscribe(q)
    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ------------------------------------------------------------------ gallery
@app.get("/api/gallery")
async def gallery(limit: int = 60, offset: int = 0, kind: str | None = None) -> dict:
    return {"images": db.list_images(limit=min(limit, 200), offset=offset, kind=kind)}


@app.get("/api/images/{image_id}/file")
async def image_file(image_id: str):
    img = db.get_image(image_id)
    if not img:
        raise HTTPException(status_code=404, detail="unknown image")
    path = storage.resolve_path(img["path"])
    if not path.exists():
        raise HTTPException(status_code=410, detail="image file missing")
    return FileResponse(path, media_type="image/png", filename=path.name)


@app.get("/api/images/{image_id}/thumb")
async def image_thumb(image_id: str):
    img = db.get_image(image_id)
    if not img:
        raise HTTPException(status_code=404, detail="unknown image")
    thumb = storage.resolve_path(img["thumb"]) if img.get("thumb") else None
    if thumb and thumb.exists():
        return FileResponse(thumb, media_type="image/jpeg")
    path = storage.resolve_path(img["path"])
    if path.exists():
        return FileResponse(path, media_type="image/png")
    raise HTTPException(status_code=410, detail="image file missing")


@app.delete("/api/images/{image_id}")
async def delete_image(image_id: str) -> dict:
    img = db.delete_image(image_id)
    if not img:
        raise HTTPException(status_code=404, detail="unknown image")
    for key in ("path", "thumb"):
        if img.get(key):
            try:
                storage.resolve_path(img[key]).unlink(missing_ok=True)
            except Exception:
                pass
    return {"ok": True}


# ------------------------------------------------------------------ settings / logs / quit
@app.get("/api/settings")
async def get_settings() -> dict:
    return _public_settings()


def _public_settings() -> dict:
    """Settings that are safe to send to the browser (the API key itself is never sent)."""
    import copy

    data = copy.deepcopy(settings)
    assistant_cfg = data.get("assistant") or {}
    key = (assistant_cfg.get("api_key") or "").strip()
    assistant_cfg["api_key"] = ""
    assistant_cfg["api_key_set"] = bool(key)
    assistant_cfg["api_key_hint"] = f"...{key[-4:]}" if len(key) >= 8 else ""
    data["assistant"] = assistant_cfg
    return data


@app.put("/api/settings")
async def put_settings(body: dict) -> dict:
    defaults = body.get("defaults")
    # Auto owns settings["defaults"]: selecting Auto resets it to the app baseline, so a
    # debounced manual-edit PUT must never overwrite that baseline.
    active_profile = (settings.get("profiles") or {}).get("active", "auto")
    if isinstance(defaults, dict) and active_profile != "auto":
        for key in ("size", "steps", "cfg", "sampler", "batch", "transparent"):
            if key in defaults:
                settings["defaults"][key] = defaults[key]
    autostart = body.get("engine_autostart")
    if isinstance(autostart, bool):
        settings["engine"]["autostart"] = autostart

    assistant_body = body.get("assistant")
    if isinstance(assistant_body, dict):
        current = settings.setdefault("assistant", {})
        if isinstance(assistant_body.get("enabled"), bool):
            current["enabled"] = assistant_body["enabled"]
        for key in ("base_url", "model"):
            value = assistant_body.get(key)
            if isinstance(value, str) and value.strip():
                current[key] = value.strip()
        if isinstance(assistant_body.get("api_key"), str) and assistant_body["api_key"].strip():
            current["api_key"] = assistant_body["api_key"].strip()
        if assistant_body.get("clear_key"):
            current["api_key"] = ""
    config.save_settings(settings)
    return _public_settings()


@app.post("/api/assistant/test")
async def assistant_test(body: dict | None = None) -> dict:
    """Check the assistant credentials (accepts unsaved values from the settings form)."""
    probe = {"assistant": dict(settings.get("assistant") or {})}
    override = (body or {}).get("assistant")
    if isinstance(override, dict):
        for key in ("base_url", "model", "api_key"):
            if isinstance(override.get(key), str) and override[key].strip():
                probe["assistant"][key] = override[key].strip()
    if not (probe["assistant"].get("api_key") or "").strip():
        raise HTTPException(status_code=400, detail="enter an API key first")
    return await assistant.test_connection(probe)


@app.get("/api/guide")
async def guide() -> dict:
    path = config.DOCS_DIR / "GUIDE.md"
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        text = "# Guide\n\nGuide content is missing (`docs/GUIDE.md`)."
    return {"markdown": text, "app": config.APP_NAME, "version": config.APP_VERSION}


@app.get("/api/logs")
async def logs(lines: int = 200) -> dict:
    path = config.LOGS_DIR / "engine.log"
    if not path.exists():
        return {"lines": []}
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        return {"lines": [f"cannot read log: {exc}"]}
    import re
    clean = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", text)
    tail = clean.splitlines()[-max(1, min(lines, 2000)):]
    return {"lines": tail}


@app.post("/api/app/quit")
async def quit_app() -> dict:
    async def shutdown() -> None:
        await asyncio.sleep(0.2)
        SHUTDOWN.set()  # release SSE streams so uvicorn can exit cleanly
        await engine.stop()
        await asyncio.sleep(0.3)
        server = _server_ref.get("server")
        if server:
            server.should_exit = True
        else:
            os._exit(0)
    asyncio.create_task(shutdown())
    return {"ok": True, "message": "shutting down"}


# ------------------------------------------------------------------ static frontend
FRONTEND = config.ROOT / "frontend"


class NoCacheStaticFiles(StaticFiles):
    """Local app: never let the browser serve a stale UI after an update."""

    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-store, must-revalidate"
        return response


app.mount("/static", NoCacheStaticFiles(directory=str(FRONTEND)), name="static")


@app.get("/")
async def index():
    return FileResponse(FRONTEND / "index.html",
                        headers={"Cache-Control": "no-store, must-revalidate"})


@app.get("/logo.png")
async def logo():
    """Canonical project logo (single asset, shared by the app and the repo)."""
    path = config.ROOT / "Logo.png"
    if not path.exists():
        raise HTTPException(status_code=404, detail="logo missing")
    return FileResponse(path, media_type="image/png")


def main() -> None:
    config.ensure_dirs()
    db.reconcile_on_start()
    uvicorn_config = uvicorn.Config(app, host=config.APP_HOST, port=config.APP_PORT,
                                    log_level="info", access_log=False,
                                    timeout_graceful_shutdown=5)
    server = uvicorn.Server(uvicorn_config)
    _server_ref["server"] = server
    server.run()


if __name__ == "__main__":
    main()
