"""Embed Microsoft WebView2 (Chromium) inside a tkinter Frame on Windows."""

from __future__ import annotations

import ctypes
import sys
import threading
from ctypes import wintypes
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import tkinter as tk

if sys.platform == "win32":
    _WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _user32.SetParent.argtypes = [wintypes.HWND, wintypes.HWND]
    _user32.SetParent.restype = wintypes.HWND
    _user32.MoveWindow.argtypes = [
        wintypes.HWND,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.BOOL,
    ]
    _user32.MoveWindow.restype = wintypes.BOOL
    _user32.EnumWindows.argtypes = [_WNDENUMPROC, wintypes.LPARAM]
    _user32.EnumWindows.restype = wintypes.BOOL
    _user32.IsWindowVisible.argtypes = [wintypes.HWND]
    _user32.IsWindowVisible.restype = wintypes.BOOL
    _user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    _user32.GetWindowTextLengthW.restype = ctypes.c_int
    _user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    _user32.GetWindowTextW.restype = ctypes.c_int
else:
    _user32 = None  # type: ignore[assignment]

_WEBVIEW_THREAD: threading.Thread | None = None
_WEBVIEW_READY = threading.Event()
_WEBVIEW_WINDOW = None
_WEBVIEW_TITLE: str | None = None
_WEBVIEW_LOCK = threading.Lock()


def is_embed_supported() -> bool:
    return sys.platform == "win32"


def _find_hwnd_by_title(title: str, *, visible_only: bool = False) -> int:
    if _user32 is None:
        return 0
    found: list[int] = []

    def callback(hwnd: int, _lparam: int) -> bool:
        if visible_only and not _user32.IsWindowVisible(hwnd):
            return True
        length = _user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buff = ctypes.create_unicode_buffer(length + 1)
        _user32.GetWindowTextW(hwnd, buff, length + 1)
        if buff.value == title:
            found.append(hwnd)
        return True

    _user32.EnumWindows(_WNDENUMPROC(callback), 0)
    return found[0] if found else 0


def _ensure_webview_loop(*, title: str, width: int, height: int) -> None:
    global _WEBVIEW_THREAD, _WEBVIEW_WINDOW, _WEBVIEW_TITLE

    with _WEBVIEW_LOCK:
        if _WEBVIEW_THREAD is not None and _WEBVIEW_THREAD.is_alive():
            _WEBVIEW_READY.wait(timeout=8.0)
            return

        import webview

        _WEBVIEW_READY.clear()
        _WEBVIEW_TITLE = title

        def runner() -> None:
            global _WEBVIEW_WINDOW
            _WEBVIEW_WINDOW = webview.create_window(
                title,
                url="about:blank",
                width=width,
                height=height,
                frameless=True,
                easy_drag=False,
                resizable=True,
            )
            _WEBVIEW_READY.set()
            webview.start(gui="edgechromium", debug=False)

        _WEBVIEW_THREAD = threading.Thread(
            target=runner,
            name="telearchive-webview2",
            daemon=True,
        )
        _WEBVIEW_THREAD.start()

    if not _WEBVIEW_READY.wait(timeout=12.0):
        raise RuntimeError("WebView2 引擎启动超时")


class EmbeddedBoardFrame:
    """
    Host WebView2 inside a tkinter container (Windows only).

    Reparents a frameless pywebview window into the tk Frame HWND.
    """

    def __init__(self, parent: tk.Misc) -> None:
        import tkinter as tk

        self._tk = tk
        self.frame = tk.Frame(parent, borderwidth=0, highlightthickness=0)
        self._host_title = f"TeleArchiveBoard_{id(self)}"
        self._child_hwnd = 0
        self._attached = False
        self._pending_url: str | None = None
        self._attach_attempts = 0

        self.frame.bind("<Configure>", self._on_configure)
        self.frame.bind("<Destroy>", self._on_destroy, add="+")

    def pack(self, **kwargs) -> None:
        self.frame.pack(**kwargs)
        self.frame.after(150, self._bootstrap)

    def grid(self, **kwargs) -> None:
        self.frame.grid(**kwargs)
        self.frame.after(150, self._bootstrap)

    def _bootstrap(self) -> None:
        if not self.frame.winfo_exists():
            return
        try:
            width = max(self.frame.winfo_width(), 480)
            height = max(self.frame.winfo_height(), 320)
            _ensure_webview_loop(
                title=self._host_title,
                width=width,
                height=height,
            )
            if self._pending_url:
                self.load_url(self._pending_url)
                self._pending_url = None
            self.frame.after(350, self._attach_to_frame)
        except Exception as exc:  # noqa: BLE001
            self._show_error(str(exc))

    def _attach_to_frame(self) -> None:
        if not self.frame.winfo_exists():
            return
        self._attach_attempts += 1
        hwnd = _find_hwnd_by_title(self._host_title)
        if not hwnd:
            if self._attach_attempts < 40:
                self.frame.after(200, self._attach_to_frame)
            else:
                self._show_error("未能将 WebView2 窗口嵌入面板（未找到宿主窗口）。")
            return
        parent_hwnd = self.frame.winfo_id()
        _user32.SetParent(hwnd, parent_hwnd)
        self._child_hwnd = hwnd
        self._attached = True
        self._resize_child()

    def _on_configure(self, _event: object = None) -> None:
        if self._attached:
            self._resize_child()

    def _resize_child(self) -> None:
        if not self._child_hwnd:
            return
        width = max(self.frame.winfo_width(), 100)
        height = max(self.frame.winfo_height(), 100)
        _user32.MoveWindow(self._child_hwnd, 0, 0, width, height, True)

    def load_url(self, url: str) -> None:
        with _WEBVIEW_LOCK:
            window = _WEBVIEW_WINDOW
        if window is not None:
            window.load_url(url)
            return
        self._pending_url = url

    def load_file(self, html_path: Path) -> None:
        self.load_url(html_path.resolve().as_uri())

    def clear(self) -> None:
        self.load_url("about:blank")

    def shutdown(self) -> None:
        self._on_destroy()

    def _on_destroy(self, _event: object = None) -> None:
        with _WEBVIEW_LOCK:
            window = _WEBVIEW_WINDOW
        if window is not None:
            try:
                window.destroy()
            except Exception:  # noqa: BLE001
                pass
        self._child_hwnd = 0
        self._attached = False

    def _show_error(self, message: str) -> None:
        for child in self.frame.winfo_children():
            child.destroy()
        label = self._tk.Label(
            self.frame,
            text=(
                "无法内嵌 WebView2 看板。\n"
                f"{message}\n\n"
                "请安装 Microsoft Edge WebView2 运行时，或使用「在浏览器中打开」。"
            ),
            justify=self._tk.LEFT,
            wraplength=360,
        )
        label.pack(fill=self._tk.BOTH, expand=True, padx=8, pady=8)
