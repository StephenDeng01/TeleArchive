"""Update reminder dialog for the GUI."""

from __future__ import annotations

import tkinter as tk
import webbrowser
from tkinter import ttk
from typing import Callable

from telearchive.updater import ReleaseInfo, dismiss_update_reminder


class UpdateDialog(tk.Toplevel):
    def __init__(
        self,
        master: tk.Misc,
        release: ReleaseInfo,
        current_version: str,
        *,
        on_later: Callable[[], None] | None = None,
        on_update_now: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(master)
        self.title("发现新版本")
        self.resizable(True, True)
        self.transient(master)
        self.grab_set()

        self._release = release
        self._on_later = on_later
        self._on_update_now = on_update_now

        frame = ttk.Frame(self, padding=16)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(
            frame,
            text=f"TeleArchive {release.version} 已发布",
            font=("Segoe UI", 13, "bold"),
        ).pack(anchor=tk.W)

        ttk.Label(
            frame,
            text=f"当前版本: {current_version}  →  最新版本: {release.version}",
        ).pack(anchor=tk.W, pady=(6, 10))

        notes = release.notes.strip() or "（无更新说明）"
        preview = notes if len(notes) <= 800 else notes[:800] + "\n…"

        notes_box = tk.Text(frame, height=10, width=56, wrap=tk.WORD, font=("Segoe UI", 10))
        notes_box.pack(fill=tk.BOTH, expand=True)
        notes_box.insert("1.0", preview)
        notes_box.configure(state=tk.DISABLED)

        ttk.Label(
            frame,
            text="此为可选更新提醒，可继续使用当前版本。",
            foreground="#666666",
        ).pack(anchor=tk.W, pady=(8, 12))

        buttons = ttk.Frame(frame)
        buttons.pack(fill=tk.X)

        ttk.Button(buttons, text="前往下载", command=self._open_download).pack(side=tk.RIGHT)
        ttk.Button(buttons, text="立即更新", command=self._update_now).pack(
            side=tk.RIGHT, padx=(0, 8)
        )
        ttk.Button(buttons, text="稍后提醒", command=self._later).pack(
            side=tk.RIGHT, padx=(0, 8)
        )
        ttk.Button(buttons, text="不再提示此版本", command=self._dismiss).pack(
            side=tk.LEFT
        )

        self.protocol("WM_DELETE_WINDOW", self._later)
        self.update_idletasks()
        self._center_over(master)

    def _center_over(self, master: tk.Misc) -> None:
        self.update_idletasks()
        width, height = self.winfo_width(), self.winfo_height()
        mx = master.winfo_rootx() + (master.winfo_width() - width) // 2
        my = master.winfo_rooty() + (master.winfo_height() - height) // 2
        self.geometry(f"+{max(mx, 0)}+{max(my, 0)}")

    def _open_download(self) -> None:
        target = self._release.download_url or self._release.url
        webbrowser.open(target)
        self.destroy()

    def _update_now(self) -> None:
        if self._on_update_now:
            self._on_update_now()
        self.destroy()

    def _later(self) -> None:
        if self._on_later:
            self._on_later()
        self.destroy()

    def _dismiss(self) -> None:
        dismiss_update_reminder(self._release.version)
        self.destroy()
