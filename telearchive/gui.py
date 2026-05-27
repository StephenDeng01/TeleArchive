"""Graphical interface for TeleArchive (tkinter, no extra dependencies)."""

from __future__ import annotations

import shutil
import sys
import threading
import tkinter as tk
from pathlib import Path
from typing import Callable
from tkinter import filedialog, messagebox, scrolledtext, ttk

from telearchive import __version__
from telearchive.coverage import export_coverage, find_id_gaps
from telearchive.db import Database
from telearchive.export_chat import export_chat_range
from telearchive.export_dates import default_datetime_bounds, set_shortcut_range
from telearchive.board_browser import show_board_html
from telearchive.board_embed import EmbeddedBoardFrame, is_embed_platform, is_embed_supported
from telearchive.webview2_runtime import (
    bootstrap_portable_runtime,
    is_runtime_ready,
    runtime_status_message,
)
from telearchive.html_board import (
    BoardRenderResult,
    render_range_to_cache,
    warmup_all_messages_cache,
)
from telearchive.merge import ingest_paths
from telearchive.notify import notify_update_available
from telearchive.update_dialog import UpdateDialog
from telearchive.updater import (
    ReleaseInfo,
    UpdateCheckResult,
    check_for_update,
    perform_in_app_update,
    should_notify_update,
)
from telearchive.paths import default_export_slice_dir
from telearchive.paths import default_db_path
from telearchive.paths import default_html_cache_dir

DEFAULT_DB = default_db_path()


def launch_gui() -> None:
    """Open the desktop window. Blocks until the user closes it."""
    if sys.platform == "win32":
        from telearchive.webview2_runtime import configure_portable_webview2

        configure_portable_webview2()
    app = TeleArchiveApp()
    app.mainloop()


class TeleArchiveApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"TeleArchive v{__version__}")
        self.minsize(720, 520)
        self.geometry("860x600")

        self.db_path = tk.StringVar(value=str(DEFAULT_DB.resolve()))
        self.export_paths: list[Path] = []
        self._busy = False
        self._board_loaded_file: Path | None = None
        self._board_bundle_dir: Path | None = None
        self._board_embed: EmbeddedBoardFrame | None = None
        self._board_cache_dir = default_html_cache_dir().resolve()

        self._build_ui()
        self._log("欢迎使用 TeleArchive。请选择 Telegram 导出文件夹，然后点击「导入合并」。")
        self._log("提示：每次导出的完整文件夹（含 result.json 与 photos/ 等）均可添加。")
        if sys.platform == "win32":
            from telearchive.webview2_runtime import runtime_status_message

            self._log(runtime_status_message())
        self.after(800, self._check_update_on_startup)

    def _build_ui(self) -> None:
        pad = {"padx": 10, "pady": 6}
        root = ttk.Frame(self, padding=8)
        root.pack(fill=tk.BOTH, expand=True)

        paned = ttk.PanedWindow(root, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True)
        left = ttk.Frame(paned, padding=12)
        right = ttk.Frame(paned, padding=10)
        paned.add(left, weight=3)
        paned.add(right, weight=2)

        # Left: existing tools
        header = ttk.Frame(left)
        header.pack(fill=tk.X, **pad)
        ttk.Label(
            header,
            text="TeleArchive",
            font=("Segoe UI", 18, "bold"),
        ).pack(side=tk.LEFT)
        ttk.Label(
            header,
            text="Telegram 群聊归档与合并",
            font=("Segoe UI", 11),
        ).pack(side=tk.LEFT, padx=(12, 0))

        # Database
        db_frame = ttk.LabelFrame(left, text="数据库文件", padding=10)
        db_frame.pack(fill=tk.X, **pad)
        ttk.Entry(db_frame, textvariable=self.db_path).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8)
        )
        ttk.Button(db_frame, text="浏览…", command=self._browse_db).pack(side=tk.RIGHT)

        # Export folders
        export_frame = ttk.LabelFrame(left, text="Telegram 导出文件夹", padding=10)
        export_frame.pack(fill=tk.BOTH, expand=False, **pad)

        list_wrap = ttk.Frame(export_frame)
        list_wrap.pack(fill=tk.BOTH, expand=True)
        self.export_list = tk.Listbox(list_wrap, height=5, font=("Consolas", 10))
        scroll = ttk.Scrollbar(list_wrap, orient=tk.VERTICAL, command=self.export_list.yview)
        self.export_list.configure(yscrollcommand=scroll.set)
        self.export_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)

        btn_row = ttk.Frame(export_frame)
        btn_row.pack(fill=tk.X, pady=(8, 0))
        ttk.Button(btn_row, text="添加文件夹", command=self._add_folder).pack(side=tk.LEFT)
        ttk.Button(btn_row, text="添加多个", command=self._add_folders).pack(
            side=tk.LEFT, padx=(8, 0)
        )
        ttk.Button(btn_row, text="移除选中", command=self._remove_selected).pack(
            side=tk.LEFT, padx=(8, 0)
        )
        ttk.Button(btn_row, text="清空", command=self._clear_folders).pack(
            side=tk.LEFT, padx=(8, 0)
        )

        # Actions
        action_row = ttk.Frame(left)
        action_row.pack(fill=tk.X, **pad)
        self.btn_init = ttk.Button(action_row, text="初始化数据库", command=self._init_db)
        self.btn_init.pack(side=tk.LEFT)
        self.btn_ingest = ttk.Button(
            action_row, text="导入合并", command=self._run_ingest, style="Accent.TButton"
        )
        self.btn_ingest.pack(side=tk.LEFT, padx=(8, 0))
        self.btn_status = ttk.Button(action_row, text="查看状态", command=self._show_status)
        self.btn_status.pack(side=tk.LEFT, padx=(8, 0))
        self.btn_gaps = ttk.Button(action_row, text="缺口分析", command=self._show_gaps)
        self.btn_gaps.pack(side=tk.LEFT, padx=(8, 0))
        self.btn_update = ttk.Button(action_row, text="检查更新", command=self._check_update_manual)
        self.btn_update.pack(side=tk.RIGHT)

        export_frame = ttk.LabelFrame(left, text="按时间导出（Telegram JSON 格式）", padding=10)
        export_frame.pack(fill=tk.X, **pad)

        export_from_default, export_to_default = default_datetime_bounds()
        self.export_from = tk.StringVar(value=export_from_default)
        self.export_to = tk.StringVar(value=export_to_default)
        self.export_out = tk.StringVar(value=str(default_export_slice_dir().resolve()))
        self.export_chat_id = tk.StringVar(value="")
        self.export_include_media = tk.BooleanVar(value=True)

        row1 = ttk.Frame(export_frame)
        row1.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(row1, text="从").pack(side=tk.LEFT)
        ttk.Entry(row1, textvariable=self.export_from, width=20).pack(
            side=tk.LEFT, padx=(4, 12)
        )
        ttk.Label(row1, text="到").pack(side=tk.LEFT)
        ttk.Entry(row1, textvariable=self.export_to, width=20).pack(
            side=tk.LEFT, padx=(4, 12)
        )
        ttk.Label(row1, text="群聊 ID（可空）").pack(side=tk.LEFT)
        ttk.Entry(row1, textvariable=self.export_chat_id, width=16).pack(
            side=tk.LEFT, padx=(4, 0)
        )
        ttk.Label(
            export_frame,
            text="时间格式 YYYY-MM-DD 或 YYYY-MM-DDTHH:MM:SS（UTC+8）",
            font=("Segoe UI", 8),
        ).pack(anchor=tk.W, pady=(0, 4))

        export_preset_row = ttk.Frame(export_frame)
        export_preset_row.pack(fill=tk.X, pady=(0, 6))
        for label, key in (
            ("今天", "today"),
            ("近三天", "3d"),
            ("近一周", "7d"),
            ("近一月", "30d"),
            ("全部消息", "all"),
        ):
            ttk.Button(
                export_preset_row,
                text=label,
                command=lambda k=key: self._set_export_shortcut(k),
            ).pack(side=tk.LEFT, padx=(0, 6))

        row2 = ttk.Frame(export_frame)
        row2.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(row2, text="输出目录").pack(side=tk.LEFT)
        ttk.Entry(row2, textvariable=self.export_out).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 8)
        )
        ttk.Button(row2, text="浏览…", command=self._browse_export_dir).pack(side=tk.RIGHT)

        row3 = ttk.Frame(export_frame)
        row3.pack(fill=tk.X)
        ttk.Checkbutton(
            row3,
            text="包含媒体文件（photos/、video_files/ 等）",
            variable=self.export_include_media,
        ).pack(side=tk.LEFT)
        self.btn_export = ttk.Button(row3, text="导出", command=self._run_export)
        self.btn_export.pack(side=tk.RIGHT)

        try:
            style = ttk.Style()
            style.configure("Accent.TButton", font=("Segoe UI", 10, "bold"))
        except tk.TclError:
            pass

        # Log
        log_frame = ttk.LabelFrame(left, text="运行日志", padding=10)
        log_frame.pack(fill=tk.BOTH, expand=True, **pad)
        self.log = scrolledtext.ScrolledText(
            log_frame,
            height=12,
            font=("Consolas", 10),
            state=tk.DISABLED,
            wrap=tk.WORD,
        )
        self.log.pack(fill=tk.BOTH, expand=True)

        # Right: HTML board
        board_frame = ttk.LabelFrame(right, text="聊天看板（HTML 渲染）", padding=10)
        board_frame.pack(fill=tk.BOTH, expand=True)
        board_from_default, board_to_default = default_datetime_bounds()
        self.board_from = tk.StringVar(value=board_from_default)
        self.board_to = tk.StringVar(value=board_to_default)

        top_row = ttk.Frame(board_frame)
        top_row.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(top_row, text="从").pack(side=tk.LEFT)
        ttk.Entry(top_row, textvariable=self.board_from, width=20).pack(
            side=tk.LEFT, padx=(4, 8)
        )
        ttk.Label(top_row, text="到").pack(side=tk.LEFT)
        ttk.Entry(top_row, textvariable=self.board_to, width=20).pack(
            side=tk.LEFT, padx=(4, 8)
        )
        ttk.Label(top_row, text="群聊ID").pack(side=tk.LEFT)
        ttk.Entry(top_row, textvariable=self.export_chat_id, width=14).pack(side=tk.LEFT, padx=(4, 8))
        self.btn_board_refresh = ttk.Button(top_row, text="刷新预览", command=self._render_board)
        self.btn_board_refresh.pack(side=tk.RIGHT)

        preset_row = ttk.Frame(board_frame)
        preset_row.pack(fill=tk.X, pady=(0, 6))
        self.btn_today = ttk.Button(
            preset_row, text="今天", command=lambda: self._set_board_shortcut("today")
        )
        self.btn_3d = ttk.Button(
            preset_row, text="近三天", command=lambda: self._set_board_shortcut("3d")
        )
        self.btn_7d = ttk.Button(
            preset_row, text="近一周", command=lambda: self._set_board_shortcut("7d")
        )
        self.btn_30d = ttk.Button(
            preset_row, text="近一月", command=lambda: self._set_board_shortcut("30d")
        )
        self.btn_all = ttk.Button(
            preset_row, text="全部消息", command=lambda: self._set_board_shortcut("all")
        )
        self.btn_board_close = ttk.Button(
            preset_row, text="关闭", command=self._close_board, style="Accent.TButton"
        )
        for btn in (self.btn_today, self.btn_3d, self.btn_7d, self.btn_30d, self.btn_all):
            btn.pack(side=tk.LEFT, padx=(0, 6))
        self.btn_board_close.pack(side=tk.RIGHT)

        board_status_row = ttk.Frame(board_frame)
        board_status_row.pack(fill=tk.X, pady=(0, 6))
        self.board_status = ttk.Label(board_status_row, text="未加载", anchor=tk.W)
        self.board_status.pack(side=tk.LEFT, fill=tk.X, expand=True)

        board_view_host = ttk.Frame(board_frame)
        board_view_host.pack(fill=tk.BOTH, expand=True, pady=(0, 6))
        if is_embed_platform():
            if is_runtime_ready():
                self._board_embed = EmbeddedBoardFrame(board_view_host)
                self._board_embed.pack(fill=tk.BOTH, expand=True)
            else:
                self._board_embed = None
                hint = scrolledtext.ScrolledText(
                    board_view_host,
                    height=12,
                    font=("Segoe UI", 10),
                    wrap=tk.WORD,
                )
                hint.pack(fill=tk.BOTH, expand=True)
                hint.insert(tk.END, runtime_status_message() + "\n")
                hint.configure(state=tk.DISABLED)
        else:
            self._board_embed = None
            fallback = scrolledtext.ScrolledText(
                board_view_host,
                height=16,
                font=("Segoe UI", 10),
                wrap=tk.WORD,
                state=tk.DISABLED,
            )
            fallback.pack(fill=tk.BOTH, expand=True)
            fallback.configure(state=tk.NORMAL)
            fallback.insert(
                tk.END,
                "当前系统不支持内嵌 WebView2，请使用「在系统浏览器中打开」。\n",
            )
            fallback.configure(state=tk.DISABLED)

        board_btn_row = ttk.Frame(board_frame)
        board_btn_row.pack(fill=tk.X)
        if is_embed_platform():
            self.btn_install_webview2 = ttk.Button(
                board_btn_row,
                text="安装便携 WebView2",
                command=self._install_portable_webview2,
            )
            self.btn_install_webview2.pack(side=tk.LEFT)
        self.btn_board_open = ttk.Button(
            board_btn_row,
            text="在系统浏览器中打开",
            command=self._open_board_in_browser,
        )
        self.btn_board_open.pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(
            board_btn_row,
            text="打开缓存目录",
            command=self._open_board_cache_dir,
        ).pack(side=tk.LEFT, padx=(8, 0))

        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self.status = ttk.Label(root, text="就绪", anchor=tk.W)
        self.status.pack(fill=tk.X, padx=10, pady=(4, 8))

    def _log(self, message: str) -> None:
        self.log.configure(state=tk.NORMAL)
        self.log.insert(tk.END, message + "\n")
        self.log.see(tk.END)
        self.log.configure(state=tk.DISABLED)

    def _set_busy(self, busy: bool, text: str) -> None:
        self._busy = busy
        state = tk.DISABLED if busy else tk.NORMAL
        for widget in (
            self.btn_init,
            self.btn_ingest,
            self.btn_status,
            self.btn_gaps,
            self.btn_update,
            self.btn_export,
            self.btn_board_refresh,
            self.btn_board_open,
            getattr(self, "btn_install_webview2", self.btn_board_open),
            self.btn_board_close,
            self.btn_today,
            self.btn_3d,
            self.btn_7d,
            self.btn_30d,
            self.btn_all,
        ):
            widget.configure(state=state)
        self.status.configure(text=text)
        self.configure(cursor="watch" if busy else "")

    def _browse_export_dir(self) -> None:
        path = filedialog.askdirectory(title="选择导出目录")
        if path:
            self.export_out.set(path)

    def _browse_db(self) -> None:
        path = filedialog.asksaveasfilename(
            title="选择数据库文件",
            defaultextension=".db",
            filetypes=[("SQLite 数据库", "*.db"), ("所有文件", "*.*")],
            initialfile="telearchive.db",
        )
        if path:
            self.db_path.set(path)

    def _add_folder(self) -> None:
        path = filedialog.askdirectory(title="选择 Telegram 导出文件夹")
        if path:
            self._append_export(path)

    def _add_folders(self) -> None:
        # tkinter has no multi-directory picker; allow repeated single picks via parent
        parent = filedialog.askdirectory(title="选择包含多个 ChatExport_* 的父文件夹")
        if not parent:
            return
        parent_path = Path(parent)
        child_exports = sorted(
            p for p in parent_path.iterdir() if p.is_dir() and (p / "result.json").is_file()
        )
        if child_exports:
            for p in child_exports:
                self._append_export(str(p))
            self._log(f"已从父目录发现 {len(child_exports)} 个导出文件夹。")
        elif (parent_path / "result.json").is_file():
            self._append_export(parent)
        else:
            messagebox.showwarning("未找到导出", "该目录下未发现 result.json。")

    def _append_export(self, path: str) -> None:
        resolved = str(Path(path).resolve())
        if resolved in self.export_paths:
            return
        self.export_paths.append(resolved)
        self.export_list.insert(tk.END, resolved)

    def _remove_selected(self) -> None:
        selection = self.export_list.curselection()
        if not selection:
            return
        idx = selection[0]
        self.export_list.delete(idx)
        del self.export_paths[idx]

    def _clear_folders(self) -> None:
        self.export_list.delete(0, tk.END)
        self.export_paths.clear()

    def _run_async(self, label: str, worker: Callable[[], None]) -> None:
        if self._busy:
            return

        def task() -> None:
            try:
                worker()
            except Exception as exc:  # noqa: BLE001 - show in GUI
                self.after(0, lambda: messagebox.showerror("错误", str(exc)))
                self.after(0, lambda: self._log(f"错误: {exc}"))
            finally:
                self.after(0, lambda: self._set_busy(False, "就绪"))

        self._set_busy(True, label)
        threading.Thread(target=task, daemon=True).start()

    def _init_db(self) -> None:
        def worker() -> None:
            db_path = Path(self.db_path.get())
            with Database(db_path) as db:
                db.init_schema()
            self.after(0, lambda: self._log(f"已初始化数据库: {db_path.resolve()}"))

        self._run_async("正在初始化…", worker)

    def _run_ingest(self) -> None:
        if not self.export_paths:
            messagebox.showinfo("提示", "请先添加至少一个 Telegram 导出文件夹。")
            return

        def worker() -> None:
            db_path = Path(self.db_path.get())
            with Database(db_path) as db:
                results = ingest_paths(db, [Path(p) for p in self.export_paths])
                chats = db.list_chat_stats()
                logical, locations, found, missing = db.media_stats()

            lines = ["", "=== 导入完成 ==="]
            for source, stats in results:
                lines.append(
                    f"· {Path(source).parent.name}: "
                    f"处理 {stats.messages_seen} 条，"
                    f"新增 {stats.messages_new}，更新 {stats.messages_updated}"
                )
            if chats:
                c = chats[0]
                lines.append(
                    f"合并后共 {c.message_count} 条唯一消息 "
                    f"（{c.name}）"
                )
            lines.append(
                f"媒体: {logical} 个附件，{locations} 条路径记录，"
                f"磁盘可用 {found}，缺失 {missing}"
            )
            if len(results) > 1 and chats:
                preserved = max(chats[0].message_count - results[-1][1].messages_seen, 0)
                if preserved:
                    lines.append(
                        f"较早导出保留、较新导出已消失的消息约 {preserved} 条"
                    )
            text = "\n".join(lines)
            self.after(0, lambda: self._log(text))
            self.after(0, self._clear_folders)
            self.after(
                0,
                lambda: messagebox.showinfo(
                    "导入完成",
                    chats[0].message_count if chats else "已完成",
                ),
            )
            if chats:
                self.after(0, lambda: self._warmup_html_cache_async(chats[0].chat_id))

        self._run_async("正在导入合并…", worker)

    def _show_status(self) -> None:
        def worker() -> None:
            db_path = Path(self.db_path.get())
            if not db_path.is_file():
                self.after(0, lambda: messagebox.showwarning("提示", "数据库不存在，请先初始化或导入。"))
                return
            with Database(db_path) as db:
                chats = db.list_chat_stats()
                imports = db.import_history(limit=5)
                logical, locations, found, missing = db.media_stats()

            lines = ["", "=== 状态概览 ==="]
            for c in chats:
                lines.append(f"群聊: {c.name} (id={c.chat_id})")
                lines.append(f"  消息数: {c.message_count}")
                if c.earliest and c.latest:
                    lines.append(f"  时间范围: {c.earliest} ~ {c.latest}")
            lines.append(
                f"媒体: 逻辑附件 {logical}，路径 {locations}，"
                f"在盘 {found}，缺失 {missing}"
            )
            if imports:
                lines.append("最近导入:")
                for row in imports:
                    lines.append(
                        f"  · {Path(row['source_path']).parent.name}: "
                        f"+{row['messages_new']} / 处理 {row['messages_seen']}"
                    )
            self.after(0, lambda: self._log("\n".join(lines)))

        self._run_async("正在读取状态…", worker)

    def _show_gaps(self) -> None:
        def worker() -> None:
            db_path = Path(self.db_path.get())
            if not db_path.is_file():
                self.after(0, lambda: messagebox.showwarning("提示", "数据库不存在。"))
                return
            with Database(db_path) as db:
                chats = db.list_chat_stats()
                if not chats:
                    self.after(0, lambda: self._log("尚无聊天记录。"))
                    return
                chat_id = chats[0].chat_id
                gaps = find_id_gaps(db._conn, chat_id, min_gap=10)
                coverage = export_coverage(db._conn, chat_id)

            lines = ["", f"=== 缺口分析: {chats[0].name} ==="]
            for row in coverage:
                lines.append(
                    f"批次 {Path(row.source_path).parent.name}: "
                    f"本批 {row.messages_seen}，首次入库 {row.messages_new}"
                )
            if gaps:
                lines.append(f"发现 {len(gaps)} 段 message id 空洞 (≥10):")
                for gap in gaps[:10]:
                    lines.append(
                        f"  id {gap.after_id} → {gap.before_id}，缺失约 {gap.missing_count} 条"
                    )
                if len(gaps) > 10:
                    lines.append(f"  … 另有 {len(gaps) - 10} 段")
            else:
                lines.append("未发现 ≥10 的空洞。")
            self.after(0, lambda: self._log("\n".join(lines)))

        self._run_async("正在分析…", worker)

    def _run_export(self) -> None:
        def worker() -> None:
            db_path = Path(self.db_path.get())
            if not db_path.is_file():
                self.after(
                    0,
                    lambda: messagebox.showwarning("提示", "数据库不存在，请先导入聊天记录。"),
                )
                return

            chat_id_text = self.export_chat_id.get().strip()
            with Database(db_path) as db:
                chats = db.list_chat_stats()
                if not chats:
                    self.after(0, lambda: messagebox.showwarning("提示", "尚无聊天记录。"))
                    return
                if chat_id_text:
                    chat_id = int(chat_id_text)
                elif len(chats) == 1:
                    chat_id = chats[0].chat_id
                else:
                    self.after(
                        0,
                        lambda: messagebox.showwarning(
                            "提示",
                            "数据库中有多个群聊，请填写群聊 ID。",
                        ),
                    )
                    return

                try:
                    result = export_chat_range(
                        db,
                        Path(self.export_out.get()),
                        chat_id,
                        from_bound=self.export_from.get().strip(),
                        to_bound=self.export_to.get().strip(),
                        include_media=self.export_include_media.get(),
                    )
                except (ValueError, OSError) as exc:
                    self.after(0, lambda: messagebox.showerror("导出失败", str(exc)))
                    return

            lines = [
                "",
                "=== 导出完成 ===",
                f"目录: {result.output_dir}",
                f"群聊: {result.chat_name}",
                f"消息: {result.message_count} 条",
                f"媒体: 复制 {result.media_copied}，缺失 {result.media_missing}",
            ]
            self.after(0, lambda: self._log("\n".join(lines)))
            self.after(
                0,
                lambda: messagebox.showinfo(
                    "导出完成",
                    f"已写入 {result.message_count} 条消息\n{result.output_dir}",
                ),
            )

        self._run_async("正在导出…", worker)

    def _set_time_shortcut(
        self,
        name: str,
        from_var: tk.StringVar,
        to_var: tk.StringVar,
        *,
        refresh_board: bool = False,
    ) -> None:
        from_text, to_text = set_shortcut_range(name)
        from_var.set(from_text)
        to_var.set(to_text)
        if refresh_board:
            self._render_board()

    def _set_export_shortcut(self, name: str) -> None:
        self._set_time_shortcut(name, self.export_from, self.export_to)

    def _set_board_shortcut(self, name: str) -> None:
        self._set_time_shortcut(
            name,
            self.board_from,
            self.board_to,
            refresh_board=True,
        )

    def _resolve_board_chat_id(self, db: Database) -> int:
        text = self.export_chat_id.get().strip()
        if text:
            return int(text)
        chats = db.list_chat_stats()
        if not chats:
            raise ValueError("数据库中没有聊天记录，请先导入。")
        if len(chats) > 1:
            raise ValueError("数据库中有多个群聊，请填写群聊ID。")
        return chats[0].chat_id

    def _install_portable_webview2(self) -> None:
        if not is_embed_platform():
            return

        def worker() -> None:
            try:
                bootstrap_portable_runtime(progress=lambda m: self.after(0, lambda: self._log(m)))
            except OSError as exc:
                self.after(0, lambda: messagebox.showerror("安装失败", str(exc)))
                return
            self.after(
                0,
                lambda: messagebox.showinfo(
                    "安装完成",
                    "便携 WebView2 已安装到程序目录（与 exe 同级）。\n"
                    "请重启应用后点击「刷新预览」。",
                ),
            )

        self._run_async("正在安装便携 WebView2…", worker)

    def _render_board(self) -> None:
        if is_embed_platform() and not is_runtime_ready() and self._board_embed is None:
            messagebox.showinfo(
                "需要 WebView2",
                "请先点击「安装便携 WebView2」，或使用带 WebView2Runtime 文件夹的完整安装包。",
            )
            return

        def worker() -> None:
            db_path = Path(self.db_path.get())
            if not db_path.is_file():
                raise ValueError("数据库不存在，请先初始化或导入。")
            with Database(db_path) as db:
                chat_id = self._resolve_board_chat_id(db)
                result = render_range_to_cache(
                    db,
                    self._board_cache_dir,
                    chat_id,
                    self.board_from.get().strip(),
                    self.board_to.get().strip(),
                )
            self.after(0, lambda: self._load_board_html(result))

        self._run_async("正在编译看板…", worker)

    def _load_board_html(self, result: BoardRenderResult) -> None:
        html_path = result.html_path.resolve()
        self._board_loaded_file = html_path
        self._board_bundle_dir = html_path.parent
        source = "缓存命中" if result.cached else "新编译"
        self.board_status.configure(
            text=(
                f"{result.chat_name} | {result.message_count} 条 | "
                f"{self.board_from.get()} ~ {self.board_to.get()} | {source}"
            )
        )
        self._log(f"看板 HTML: {html_path} ({source})")
        if self._board_embed is not None:
            try:
                self._board_embed.load_file(html_path)
                self._log("看板已在内嵌 WebView2 中加载。")
                self.after(2200, self._verify_embedded_board_ready)
            except Exception as exc:  # noqa: BLE001
                messagebox.showerror("内嵌看板失败", str(exc))
                self._log(f"内嵌看板失败: {exc}")
        else:
            try:
                note = show_board_html(html_path)
                self._log(note)
            except Exception as exc:  # noqa: BLE001
                messagebox.showerror("打开看板失败", str(exc))

    def _open_board_in_browser(self) -> None:
        if self._board_loaded_file is None or not self._board_loaded_file.is_file():
            messagebox.showinfo("提示", "请先点击「刷新预览」生成看板。")
            return
        try:
            note = show_board_html(self._board_loaded_file)
            self._log(note)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("打开看板失败", str(exc))

    def _open_board_cache_dir(self) -> None:
        cache = self._board_cache_dir
        if not cache.is_dir():
            messagebox.showinfo("提示", "尚无看板缓存。")
            return
        if sys.platform == "win32":
            import os

            os.startfile(cache)  # noqa: S606
        else:
            messagebox.showinfo("缓存目录", str(cache))

    def _close_board(self) -> None:
        if self._board_embed is not None:
            self._board_embed.clear()
        if self._board_loaded_file is not None:
            bundle_dir = self._board_loaded_file.parent
            try:
                shutil.rmtree(bundle_dir, ignore_errors=True)
            except OSError:
                pass
        self._board_loaded_file = None
        self._board_bundle_dir = None
        self.board_status.configure(text="未加载")

    def _verify_embedded_board_ready(self) -> None:
        if self._board_embed is None or self._board_loaded_file is None:
            return
        if self._board_embed.is_attached():
            return
        note = self._board_embed.last_error() or "内嵌失败，自动切换到系统浏览器。"
        self._log(f"看板内嵌失败: {note}")
        try:
            browser_note = show_board_html(self._board_loaded_file)
            self._log(browser_note)
            self.board_status.configure(text=f"{self.board_status.cget('text')} | 浏览器兜底")
        except Exception as exc:  # noqa: BLE001
            self._log(f"浏览器兜底也失败: {exc}")

    def _on_close(self) -> None:
        if self._board_embed is not None:
            self._board_embed.shutdown()
        self.quit()
        self.after(80, self.destroy)

    def _warmup_html_cache_async(self, chat_id: int) -> None:
        db_path = Path(self.db_path.get())
        cache_dir = self._board_cache_dir

        def worker() -> None:
            try:
                warmup_all_messages_cache(db_path, cache_dir, chat_id)
                self.after(0, lambda: self._log("后台缓存：已完成全量 HTML 编译。"))
            except Exception as exc:  # noqa: BLE001
                self.after(0, lambda: self._log(f"后台缓存：编译失败（可忽略）: {exc}"))

        threading.Thread(target=worker, daemon=True).start()

    def _check_update_on_startup(self) -> None:
        def worker() -> None:
            result = check_for_update()
            if should_notify_update(result):
                self.after(0, lambda: self._present_update(result, quiet=True))

        threading.Thread(target=worker, daemon=True).start()

    def _check_update_manual(self) -> None:
        def worker() -> None:
            result = check_for_update()
            self.after(0, lambda: self._handle_manual_update_result(result))

        self._run_async("正在检查更新…", worker)

    def _handle_manual_update_result(self, result: UpdateCheckResult) -> None:
        if result.error:
            messagebox.showwarning("检查更新", result.error)
            return
        if not result.has_update:
            messagebox.showinfo(
                "检查更新",
                f"当前已是最新版本（v{result.current_version}）。",
            )
            return
        self._present_update(result, quiet=False)

    def _present_update(self, result: UpdateCheckResult, *, quiet: bool) -> None:
        if not result.latest:
            return
        if quiet:
            notify_update_available(
                "TeleArchive 更新",
                f"新版本 v{result.latest.version} 已发布，点击查看。",
            )
            self._log(f"发现新版本 v{result.latest.version}，已弹出更新提醒。")
        UpdateDialog(
            self,
            result.latest,
            result.current_version,
            on_later=lambda: None,
            on_update_now=lambda: self._update_now(result.latest),
        )

    def _update_now(self, release: ReleaseInfo) -> None:
        if self._busy:
            return

        def task() -> None:
            try:
                perform_in_app_update(release)
            except RuntimeError as exc:
                self.after(0, lambda: messagebox.showwarning("立即更新", str(exc)))
                self.after(0, lambda: self._set_busy(False, "就绪"))
                return
            except Exception as exc:  # noqa: BLE001
                self.after(0, lambda: messagebox.showerror("立即更新失败", str(exc)))
                self.after(0, lambda: self._set_busy(False, "就绪"))
                return

            self.after(0, lambda: self._log("更新包已验证并准备替换，应用即将重启…"))
            # Brief delay so the detached updater can start before the exe is torn down.
            self.after(400, self._shutdown_for_restart)

        self._set_busy(True, "正在下载并更新…")
        threading.Thread(target=task, daemon=True).start()

    def _shutdown_for_restart(self) -> None:
        self.quit()
        self.destroy()


def should_launch_gui(argv: list[str] | None = None) -> bool:
    """True when the app should open the desktop UI instead of the CLI."""
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        return True
    if args == ["--gui"] or args == ["gui"]:
        return True
    return False
