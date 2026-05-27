"""Runtime helpers for PyInstaller-frozen Windows builds."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

_PYI_DIRNAME = "_pyi"


def pyi_runtime_roots() -> list[Path]:
    """Directories where onefile builds may extract ``_MEI*`` folders."""
    roots: list[Path] = []
    if os.name == "nt":
        local = os.environ.get("LOCALAPPDATA")
        if local:
            roots.append(Path(local) / "TeleArchive" / _PYI_DIRNAME)
    if getattr(sys, "frozen", False):
        roots.append(Path(sys.executable).resolve().parent)
    return roots


def cleanup_stale_pyi_extracts() -> None:
    """Remove leftover ``_MEI*`` folders from previous runs or failed updates."""
    if not getattr(sys, "frozen", False):
        return

    current = getattr(sys, "_MEIPASS", None)
    current_path = Path(current).resolve() if current else None

    for root in pyi_runtime_roots():
        if not root.is_dir():
            continue
        for entry in root.glob("_MEI*"):
            try:
                resolved = entry.resolve()
            except OSError:
                continue
            if current_path is not None and resolved == current_path:
                continue
            shutil.rmtree(entry, ignore_errors=True)
