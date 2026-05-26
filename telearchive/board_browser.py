"""Show HTML chat board in a real browser engine (WebView2 on Windows)."""

from __future__ import annotations

import sys
import threading
import time
import webbrowser
from pathlib import Path

_BOARD_WINDOW = None
_BOARD_THREAD: threading.Thread | None = None
_READY = threading.Event()
_LOCK = threading.Lock()


def show_board_html(html_path: Path) -> str:
    """
    Open or refresh the board window for ``messages.html``.

    Returns a short status string for the GUI log.
    """
    path = html_path.resolve()
    if not path.is_file():
        raise FileNotFoundError(f"看板 HTML 不存在: {path}")

    uri = path.as_uri()
    if sys.platform == "win32":
        try:
            _show_pywebview(uri)
            return f"已在应用内浏览器打开: {path}"
        except Exception as exc:  # noqa: BLE001
            webbrowser.open(uri)
            return f"WebView 不可用 ({exc})，已用系统浏览器打开: {path}"

    webbrowser.open(uri)
    return f"已在系统浏览器打开: {path}"


def close_board_html() -> None:
    """Close the embedded board window if it is open."""
    global _BOARD_WINDOW
    with _LOCK:
        window = _BOARD_WINDOW
    if window is None:
        return
    try:
        window.destroy()
    except Exception:  # noqa: BLE001
        pass
    with _LOCK:
        _BOARD_WINDOW = None


def _show_pywebview(uri: str) -> None:
    import webview

    global _BOARD_WINDOW, _BOARD_THREAD

    _ensure_pywebview_thread(webview)

    deadline = time.time() + 8.0
    while time.time() < deadline:
        with _LOCK:
            window = _BOARD_WINDOW
        if window is not None:
            break
        time.sleep(0.05)

    with _LOCK:
        window = _BOARD_WINDOW
    if window is None:
        raise RuntimeError("浏览器窗口启动超时")

    window.set_title("聊天看板 - TeleArchive")
    window.load_url(uri)


def _ensure_pywebview_thread(webview: object) -> None:
    global _BOARD_THREAD, _BOARD_WINDOW

    with _LOCK:
        if _BOARD_THREAD is not None and _BOARD_THREAD.is_alive():
            return

        _READY.clear()

        def runner() -> None:
            global _BOARD_WINDOW
            with _LOCK:
                _BOARD_WINDOW = webview.create_window(
                    "聊天看板 - TeleArchive",
                    url="about:blank",
                    width=980,
                    height=760,
                )
            _READY.set()
            webview.start(gui="edgechromium", debug=False)

        _BOARD_THREAD = threading.Thread(target=runner, name="board-webview", daemon=True)
        _BOARD_THREAD.start()

    _READY.wait(timeout=8.0)
