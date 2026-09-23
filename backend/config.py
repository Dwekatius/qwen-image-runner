"""Qwen Image Runner — configuration, paths, settings and engine backends."""
from __future__ import annotations

import json
import os
from pathlib import Path

APP_NAME = "Qwen Image Runner"
APP_VERSION = "1.2.0"
SPDX_LICENSE = "GPL-3.0-only"

ROOT = Path(__file__).resolve().parent.parent

ENGINE_ROOT = ROOT / "engine"
MODELS_DIR = ROOT / "models"
INPUTS_DIR = ROOT / "inputs"
OUTPUTS_DIR = ROOT / "outputs"
THUMBS_DIR = ROOT / "thumbnails"
DATA_DIR = ROOT / "data"
LOGS_DIR = ROOT / "logs"
DOCS_DIR = ROOT / "docs"

DB_PATH = DATA_DIR / "canvas.db"
SETTINGS_PATH = ROOT / "settings.json"
ENGINE_MANIFEST = ROOT / "engine.json"
MODELS_MANIFEST = ROOT / "models.json"


def _env(name: str, default: str) -> str:
    """Read QIR_* with a fallback to the old QCANVAS_* names."""
    return os.environ.get(f"QIR_{name}", os.environ.get(f"QCANVAS_{name}", default))


APP_HOST = "127.0.0.1"
APP_PORT = int(_env("PORT", "7878"))
ENGINE_HOST = "127.0.0.1"
ENGINE_PORT = int(_env("ENGINE_PORT", "1235"))

# ---------------------------------------------------------------- engine backends
BACKENDS: dict[str, dict] = {
    "cuda": {
        "label": "NVIDIA CUDA (recommended)",
        "detail": "Fastest option. Needs an NVIDIA GPU; the CUDA runtime DLLs are downloaded with it.",
        "dir": "engine/sd-cuda12",
        "exe": "engine/sd-cuda12/sd-server.exe",
        "assets": ["windows-cuda12", "cudart-cu12"],
        "args": ["--diffusion-fa", "--sage-attn", "--offload-to-cpu", "--cfg-scale", "6.0"],
        "speed": "1024x1024 in ~50 s (RTX 5070 Ti, 20 steps)",
    },
    "vulkan": {
        "label": "Vulkan (AMD / Intel / other GPUs)",
        "detail": "Works on most GPUs through the Vulkan driver. Slower than CUDA, much faster than CPU.",
        "dir": "engine/sd-vulkan",
        "exe": "engine/sd-vulkan/sd-server.exe",
        "assets": ["windows-vulkan"],
        "args": ["--cfg-scale", "6.0"],
        "speed": "tens of seconds to a few minutes per image, depending on the GPU",
    },
    "cpu": {
        "label": "CPU only (no GPU - very slow)",
        "detail": ("Runs without any GPU. Expect tens of minutes per image at 1024x1024 - use smaller "
                   "sizes, fewer steps, and consider a smaller model quant."),
        "dir": "engine/sd-cpu",
        "exe": "engine/sd-cpu/sd-server.exe",
        "assets": ["windows-cpu"],
        "args": ["--cfg-scale", "6.0"],
        "speed": "measured: 128 s/step at 512x512 on a Ryzen 5 5600G (plus ~4 min prompt encoding)",
    },
}
DEFAULT_BACKEND = "cuda"

# extra args that older installs stored in settings (now built into the backend specs)
_LEGACY_EXTRA_ARGS = [["--diffusion-fa", "--sage-attn", "--offload-to-cpu", "--cfg-scale", "6.0"],
                      ["--diffusion-fa", "--offload-to-cpu", "--cfg-scale", "6.0"]]

DEFAULT_SETTINGS: dict = {
    "schema_version": 2,
    "engine": {
        "autostart": True,
        "backend": DEFAULT_BACKEND,
        "diffusion_model": "models/diffusion/qwen_image_2.1-Q8_0.gguf",
        "text_encoder": "models/text_encoders/Qwen3VL-8B-Instruct-Q4_K_M.gguf",
        "vision_projector": "models/text_encoders/mmproj-Qwen3VL-8B-Instruct-F16.gguf",
        "vae": "models/vae/qwen_image_2.1_vae_bf16.safetensors",
        "extra_args": [],
    },
    "defaults": {
        "size": "1024x1024",
        "steps": 40,
        "cfg": 6.0,
        "sampler": "euler",
        "batch": 1,
        "transparent": False,
    },
    "assistant": {
        "enabled": False,
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-chat",
        "api_key": "",
    },
    "profiles": {
        "active": "auto",
        "items": [],
    },
    "license_accepted": False,
}


def ensure_dirs() -> None:
    for d in (MODELS_DIR, INPUTS_DIR, OUTPUTS_DIR, THUMBS_DIR, DATA_DIR, LOGS_DIR, DOCS_DIR):
        d.mkdir(parents=True, exist_ok=True)


def load_settings() -> dict:
    ensure_dirs()
    data: dict = {}
    if SETTINGS_PATH.exists():
        try:
            data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    merged = json.loads(json.dumps(DEFAULT_SETTINGS))  # deep copy
    for section, values in data.items():
        if isinstance(values, dict) and isinstance(merged.get(section), dict):
            merged[section].update(values)
        else:
            merged[section] = values
    # migrate: backend flags moved out of settings into the backend specs
    extra = merged.get("engine", {}).get("extra_args")
    if extra in _LEGACY_EXTRA_ARGS:
        merged["engine"]["extra_args"] = []
    merged["schema_version"] = DEFAULT_SETTINGS["schema_version"]
    # Auto mode means the assistant manages settings from the app baseline; any values
    # left over from manual editing must not silently become the Auto fallback.
    if (merged.get("profiles") or {}).get("active", "auto") == "auto":
        merged["defaults"] = json.loads(json.dumps(DEFAULT_SETTINGS["defaults"]))
    return merged


def save_settings(settings: dict) -> None:
    ensure_dirs()
    tmp = SETTINGS_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    tmp.replace(SETTINGS_PATH)


def load_manifest(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


# ---------------------------------------------------------------- backend helpers
def backend_spec(settings: dict) -> dict:
    name = (settings.get("engine", {}) or {}).get("backend") or DEFAULT_BACKEND
    return BACKENDS.get(name, BACKENDS[DEFAULT_BACKEND])


def backend_exe(settings: dict) -> Path:
    return ROOT / backend_spec(settings)["exe"]


def backend_dir(settings: dict) -> Path:
    return ROOT / backend_spec(settings)["dir"]


def backend_args(settings: dict) -> list[str]:
    spec = backend_spec(settings)
    return list(spec["args"]) + list((settings.get("engine", {}) or {}).get("extra_args") or [])


def in_fake_mode() -> bool:
    """MockEngine mode for tests / GPU-less UI development."""
    return _env("FAKE_ENGINE", "").strip().lower() in ("1", "true", "yes")
