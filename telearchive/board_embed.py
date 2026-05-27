"""Embed Microsoft WebView2 (Chromium) inside a tkinter Frame on Windows."""

from __future__ import annotations

import ctypes
import sys
import threading
from ctypes import wintypes
from pathlib import Path
from typing import TYPE_CHECKING

from telearchive.webview2_runtime import configure_portable_webview2, is_runtime_ready

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
    _user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    _user32.FindWindowW.restype = wintypes.HWND
    _user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
    _user32.GetWindowLongPtrW.restype = ctypes.c_size_t
    _user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_size_t]
    _user32.SetWindowLongPtrW.restype = ctypes.c_size_t
    _user32.SetWindowPos.argtypes = [
        wintypes.HWND,
        wintypes.HWND,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.UINT,
    ]
    _user32.SetWindowPos.restype = wintypes.BOOL
    _user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    _user32.ShowWindow.restype = wintypes.BOOL
    _user32.GetParent.argtypes = [wintypes.HWND]
    _user32.GetParent.restype = wintypes.HWND
else:
    _user32 = None  # type: ignore[assignment]

_GWL_STYLE = -16
_WS_POPUP = 0x80000000
_WS_CHILD = 0x40000000
_SWP_FRAMECHANGED = 0x0020
_SWP_NOZORDER = 0x0004
_SWP_NOMOVE = 0x0002
_SWP_NOSIZE = 0x0001
_SW_SHOW = 5

_WEBVIEW_THREAD: threading.Thread | None = None
_WEBVIEW_READY = threading.Event()
_WEBVIEW_WINDOW = None
_WEBVIEW_TITLE: str | None = None
_WEBVIEW_LOCK = threading.Lock()


def is_embed_supported() -> bool:
    return sys.platform == "win32" and is_runtime_ready()


def is_embed_platform() -> bool:
    return sys.platform == "win32"


def _find_hwnd_by_title(title: str) -> int:
    if _user32 is None:
        return 0
    hwnd = int(_user32.FindWindowW(None, title))
    if hwnd:
        return hwnd

    found: list[int] = []
    prefix_matches: list[int] = []

    def callback(hwnd: int, _lparam: int) -> bool:
        length = _user32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return True
        buff = ctypes.create_unicode_buffer(length + 1)
        _user32.GetWindowTextW(hwnd, buff, length + 1)
        text = buff.value
        if text == title:
            found.append(hwnd)
        elif text.startswith("TeleArchiveBoard_"):
            prefix_matches.append(hwnd)
        return True

    _user32.EnumWindows(_WNDENUMPROC(callback), 0)
    if found:
        return found[0]
    if prefix_matches:
        return prefix_matches[-1]
    return 0


def _apply_embedded_child_style(hwnd: int) -> None:
    """Reparented top-level windows usually need WS_CHILD and no WS_POPUP."""
    if _user32 is None or not hwnd:
        return
    try:
        style = int(_user32.GetWindowLongPtrW(hwnd, _GWL_STYLE))
        if not style:
            return
        new_style = (style | _WS_CHILD) & ~_WS_POPUP
        if new_style == style:
            return
        _user32.SetWindowLongPtrW(hwnd, _GWL_STYLE, ctypes.c_size_t(new_style))
        flags = _SWP_NOMOVE | _SWP_NOSIZE | _SWP_NOZORDER | _SWP_FRAMECHANGED
        _user32.SetWindowPos(hwnd, None, 0, 0, 0, 0, flags)
    except OSError:
        pass


def _ensure_webview_loop(*, title: str, width: int, height: int) -> None:
    global _WEBVIEW_THREAD, _WEBVIEW_WINDOW, _WEBVIEW_TITLE

    with _WEBVIEW_LOCK:
        if _WEBVIEW_THREAD is not None and _WEBVIEW_THREAD.is_alive():
            _WEBVIEW_READY.wait(timeout=8.0)
            return

        if not configure_portable_webview2():
            raise RuntimeError(
                "未找到便携 WebView2（msedgewebview2.exe）。\n"
                "请将 zip 内 TeleArchive.exe 与 WebView2Runtime 文件夹解压到同一目录。"
            )

        _WEBVIEW_READY.clear()
        _WEBVIEW_TITLE = title

        def runner() -> None:
            global _WEBVIEW_WINDOW
            if sys.platform == "win32":
                ole32 = ctypes.windll.ole32
                COINIT_APARTMENTTHREADED = 0x2
                RPC_E_CHANGED_MODE = -2147417850
                hr = ole32.CoInitializeEx(None, COINIT_APARTMENTTHREADED)
                if hr < 0 and hr != RPC_E_CHANGED_MODE:
                    pass

            import webview

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

    if not _WEBVIEW_READY.wait(timeout=20.0):
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
        self._last_error = ""
        self._pending_url: str | None = None
        self._attach_attempts = 0

        self.frame.bind("<Configure>", self._on_configure)
        self.frame.bind("<Destroy>", self._on_destroy, add="+")

    def pack(self, **kwargs) -> None:
        self.frame.pack(**kwargs)
        self.frame.after(200, self._bootstrap)

    def grid(self, **kwargs) -> None:
        self.frame.grid(**kwargs)
        self.frame.after(200, self._bootstrap)

    def _bootstrap(self) -> None:
        if not self.frame.winfo_exists():
            return
        try:
            self.frame.update_idletasks()
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
            self.frame.after(500, self._attach_to_frame)
        except Exception as exc:  # noqa: BLE001
            self._show_error(str(exc))

    def _attach_to_frame(self) -> None:
        if not self.frame.winfo_exists() or _user32 is None:
            return
        self._attach_attempts += 1
        hwnd = _find_hwnd_by_title(self._host_title)
        if not hwnd:
            if self._attach_attempts < 100:
                self.frame.after(250, self._attach_to_frame)
            else:
                self._show_error(
                    "未能找到 WebView2 宿主窗口（标题匹配失败）。\n"
                    "请确认已解压 WebView2Runtime，或尝试以管理员身份运行。"
                )
            return
        parent_hwnd = int(self.frame.winfo_id())
        _user32.SetParent(hwnd, parent_hwnd)
        if int(_user32.GetParent(hwnd)) != parent_hwnd:
            if self._attach_attempts < 100:
                self.frame.after(250, self._attach_to_frame)
            return
        _apply_embedded_child_style(hwnd)
        _user32.ShowWindow(hwnd, _SW_SHOW)
        self._child_hwnd = hwnd
        self._attached = True
        self._last_error = ""
        self._resize_child()

    def _on_configure(self, _event: object = None) -> None:
        if self._attached:
            self._resize_child()

    def _resize_child(self) -> None:
        if not self._child_hwnd or _user32 is None:
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
        # Do not synchronously destroy WebView here; that can block tkinter close
        # for several seconds on some Windows machines.
        self._child_hwnd = 0
        self._attached = False

    def is_attached(self) -> bool:
        return self._attached

    def last_error(self) -> str:
        return self._last_error

    def _show_error(self, message: str) -> None:
        self._last_error = message
        for child in self.frame.winfo_children():
            child.destroy()
        label = self._tk.Label(
            self.frame,
            text=(
                "无法内嵌 WebView2 看板。\n"
                f"{message}\n\n"
                "请确认 zip 内 exe 与 WebView2Runtime 在同一文件夹；"
                "或使用「在系统浏览器中打开」。"
            ),
            justify=self._tk.LEFT,
            wraplength=420,
        )
        label.pack(fill=self._tk.BOTH, expand=True, padx=8, pady=8)
