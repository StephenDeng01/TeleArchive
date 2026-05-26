"""Path helpers for default storage locations.

Windows user requirement:
- Prefer `E:/tg_chat_history/` for database and settings.
- If `E:` is not available or cannot be created, fall back to local `data/`.
"""

from __future__ import annotations

import os
from pathlib import Path


def _try_ensure_dir(p: Path) -> bool:
    try:
        p.mkdir(parents=True, exist_ok=True)
        return True
    except OSError:
        return False


def default_base_dir() -> Path:
    """Return base directory for local data files."""
    if os.name == "nt":
        e_root = Path("E:/tg_chat_history")
        # Only attempt if drive exists and we can create the folder.
        try:
            if Path("E:/").exists() and _try_ensure_dir(e_root):
                return e_root
        except OSError:
            pass
    return Path("data")


def default_db_path() -> Path:
    return default_base_dir() / "telearchive.db"


def default_settings_path() -> Path:
    return default_base_dir() / "settings.json"


def default_export_base_dir() -> Path:
    """Return base directory for exported slices.

    Prefer `E:/tg_export/` on Windows and create it if possible.
    Fall back to local `./exports/` otherwise.
    """
    if os.name == "nt":
        e_root = Path("E:/tg_export")
        try:
            if Path("E:/").exists() and _try_ensure_dir(e_root):
                return e_root
        except OSError:
            pass
    return Path("exports")


def default_export_slice_dir() -> Path:
    """Default directory for time-range export output."""
    return default_export_base_dir() / "export_slice"

