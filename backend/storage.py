"""Qwen Image Runner — file storage: assets, outputs, thumbnails (atomic writes)."""
from __future__ import annotations

import io
import time
import uuid
from pathlib import Path

from PIL import Image

from . import config

THUMB_SIZE = (512, 512)


def _safe_name(ext: str) -> str:
    return f"{int(time.time())}-{uuid.uuid4().hex[:8]}{ext}"


def save_input(data: bytes, ext: str = ".png") -> Path:
    """Persist an uploaded reference/mask image under inputs/."""
    config.ensure_dirs()
    path = config.INPUTS_DIR / _safe_name(ext)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)
    return path


def chat_folder(chat_id: str) -> Path:
    folder = config.OUTPUTS_DIR / "chats" / chat_id
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def save_output(data: bytes, mode: str = "generate", ext: str = ".png",
                chat_id: str | None = None) -> Path:
    """Persist a generated image. Chat images go to outputs/chats/<chat_id>/,
    everything else to outputs/YYYY-MM-DD/."""
    config.ensure_dirs()
    folder = chat_folder(chat_id) if chat_id else (config.OUTPUTS_DIR / time.strftime("%Y-%m-%d"))
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / _safe_name(ext)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)
    return path


def move_image_into_chat(stored_path: str, chat_id: str) -> str | None:
    """Move an existing output image into the chat's folder; returns the new stored path."""
    src = resolve_path(stored_path)
    if not src.exists():
        return None
    target_dir = chat_folder(chat_id)
    if src.parent == target_dir:
        return stored_path
    dst = target_dir / src.name
    src.replace(dst)
    return store_path(dst)


def store_path(path: Path | str) -> str:
    """Return a path relative to ROOT when possible, otherwise absolute."""
    p = Path(path).resolve()
    try:
        return str(p.relative_to(config.ROOT.resolve()))
    except ValueError:
        return str(p)


def resolve_path(stored: str | Path) -> Path:
    """Resolve a stored path (relative to ROOT or absolute) to a real Path."""
    p = Path(stored)
    return p if p.is_absolute() else (config.ROOT / p)


def make_thumbnail(image_path: Path, thumb_id: str | None = None) -> Path | None:
    try:
        config.ensure_dirs()
        thumb_id = thumb_id or uuid.uuid4().hex[:12]
        path = config.THUMBS_DIR / f"{thumb_id}.jpg"
        with Image.open(image_path) as im:
            im = im.convert("RGBA")
            # composite on dark background so transparency reads correctly
            bg = Image.new("RGBA", im.size, (18, 20, 26, 255))
            bg.alpha_composite(im)
            bg = bg.convert("RGB")
            bg.thumbnail(THUMB_SIZE)
            tmp = path.with_suffix(".jpg.tmp")
            bg.save(tmp, "JPEG", quality=88)
            tmp.replace(path)
        return path
    except Exception:
        return None


def image_meta(image_path: Path) -> dict:
    """Lightweight metadata for a saved output."""
    meta: dict = {}
    try:
        with Image.open(image_path) as im:
            meta["width"], meta["height"] = im.size
            meta["mode"] = im.mode
            if "parameters" in im.info:
                meta["png_parameters"] = im.info["parameters"]
    except Exception:
        pass
    return meta


def is_meaningfully_transparent(image_path: Path, threshold: int = 16) -> bool:
    """True when the image has real transparency (used for checkerboard UI)."""
    try:
        with Image.open(image_path) as im:
            if im.mode != "RGBA":
                return False
            alpha = im.getchannel("A")
            hist = alpha.histogram()
            below = sum(hist[:threshold])
            return below > (im.width * im.height) * 0.01
    except Exception:
        return False


def read_bytes(path: Path) -> bytes:
    return Path(path).read_bytes()
