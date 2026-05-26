"""Fallback helpers when embedded WebView2 is unavailable."""

from __future__ import annotations

import sys
import webbrowser
from pathlib import Path


def show_board_html(html_path: Path) -> str:
    """Open the board HTML in the system browser (fallback)."""
    path = html_path.resolve()
    if not path.is_file():
        raise FileNotFoundError(f"看板 HTML 不存在: {path}")
    uri = path.as_uri()
    webbrowser.open(uri)
    if sys.platform == "win32":
        return f"已在系统浏览器打开: {path}"
    return f"已在浏览器打开: {path}"


def close_board_html() -> None:
    """No-op for external browser fallback."""
