"""Qwen Image Runner — native Windows 'Save as' dialog + export helper.

Uses the Win32 common dialog (comdlg32.GetSaveFileNameW) so the user gets the
real Windows save dialog with folder browsing. Falls back to the export folder
in MockEngine/test mode (no dialog).
"""
from __future__ import annotations

import ctypes
import os
import shutil
from ctypes import wintypes
from pathlib import Path
from typing import Optional

from . import config

MAX_PATH_LEN = 1024
OFN_OVERWRITEPROMPT = 0x00000002
OFN_PATHMUSTEXIST = 0x00000800
OFN_EXPLORER = 0x00080000
OFN_NOCHANGEDIR = 0x00000008


class OPENFILENAMEW(ctypes.Structure):
    _fields_ = [
        ("lStructSize", wintypes.DWORD),
        ("hwndOwner", wintypes.HWND),
        ("hInstance", wintypes.HINSTANCE),
        ("lpstrFilter", wintypes.LPCWSTR),
        ("lpstrCustomFilter", wintypes.LPWSTR),
        ("nMaxCustFilter", wintypes.DWORD),
        ("nFilterIndex", wintypes.DWORD),
        ("lpstrFile", wintypes.LPWSTR),
        ("nMaxFile", wintypes.DWORD),
        ("lpstrFileTitle", wintypes.LPWSTR),
        ("nMaxFileTitle", wintypes.DWORD),
        ("lpstrInitialDir", wintypes.LPCWSTR),
        ("lpstrTitle", wintypes.LPCWSTR),
        ("Flags", wintypes.DWORD),
        ("nFileOffset", wintypes.WORD),
        ("nFileExtension", wintypes.WORD),
        ("lpstrDefExt", wintypes.LPCWSTR),
        ("lCustData", wintypes.LPARAM),
        ("lpfnHook", ctypes.c_void_p),
        ("lpTemplateName", wintypes.LPCWSTR),
        ("pvReserved", ctypes.c_void_p),
        ("dwReserved", wintypes.DWORD),
        ("FlagsEx", wintypes.DWORD),
    ]


def pick_save_path(default_name: str, title: str = "Save image") -> Optional[str]:
    """Open the native save dialog. Returns the chosen path or None if cancelled."""
    if os.name != "nt":
        return None
    buffer = ctypes.create_unicode_buffer(default_name, MAX_PATH_LEN)
    filters = "PNG image\0*.png\0JPEG image\0*.jpg;*.jpeg\0All files\0*.*\0\0"
    ofn = OPENFILENAMEW()
    ofn.lStructSize = ctypes.sizeof(OPENFILENAMEW)
    ofn.hwndOwner = None
    ofn.lpstrFilter = filters
    ofn.nFilterIndex = 1
    ofn.lpstrFile = ctypes.cast(buffer, wintypes.LPWSTR)
    ofn.nMaxFile = MAX_PATH_LEN
    ofn.lpstrTitle = title
    ofn.lpstrDefExt = "png"
    ofn.Flags = OFN_OVERWRITEPROMPT | OFN_PATHMUSTEXIST | OFN_EXPLORER | OFN_NOCHANGEDIR
    ok = ctypes.windll.comdlg32.GetSaveFileNameW(ctypes.byref(ofn))
    if not ok:
        return None
    return buffer.value or None


def export_folder() -> Path:
    """Destination used in MockEngine/test mode instead of a dialog."""
    folder = config.OUTPUTS_DIR / "saved-as"
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def suggested_name(prompt: str | None, seed, ext: str = ".png") -> str:
    import re

    base = re.sub(r"[^A-Za-z0-9 _-]+", "", prompt or "").strip()
    base = re.sub(r"\s+", "-", base)[:48].strip("-") or "qwen-image-runner"
    suffix = f"-{seed}" if seed is not None else ""
    return f"{base}{suffix}{ext}"


def save_image(src: Path, dest: Path) -> Path:
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dest)
    return dest
