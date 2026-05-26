"""Graphical interface for TeleArchive (tkinter, no extra dependencies)."""

from __future__ import annotations

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
from telearchive.merge import ingest_paths
from telearchive.notify import notify_update_available
from telearchive.update_dialog import UpdateDialog
from telearchive.updater import (
    UpdateCheckResult,
    check_for_update,
    should_notify_update,
)


DEFAULT_DB = Path("data/telearchive.db")


def launch_gui() -> None:
    """Open the desktop window. Blocks until the user closes it."""
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

        self._build_ui()
        self._log("欢迎使用 TeleArchive。请选择 Telegram 导出文件夹，然后点击「导入合并」。")
        self._log("提示：每次导出的完整文件夹（含 result.json 与 photos/ 等）均可添加。")
        self.after(800, self._check_update_on_startup)

    def _build_ui(self) -> None:
        pad = {"padx": 10, "pady": 6}
        root = ttk.Frame(self, padding=12)
        root.pack(fill=tk.BOTH, expand=True)

        # Header
        header = ttk.Frame(root)
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
        db_frame = ttk.LabelFrame(root, text="数据库文件", padding=10)
        db_frame.pack(fill=tk.X, **pad)
        ttk.Entry(db_frame, textvariable=self.db_path).pack(
            side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8)
        )
        ttk.Button(db_frame, text="浏览…", command=self._browse_db).pack(side=tk.RIGHT)

        # Export folders
        export_frame = ttk.LabelFrame(root, text="Telegram 导出文件夹", padding=10)
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
        action_row = ttk.Frame(root)
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

        export_frame = ttk.LabelFrame(root, text="按时间导出（Telegram JSON 格式）", padding=10)
        export_frame.pack(fill=tk.X, **pad)

        self.export_from = tk.StringVar(value="2026-05-01")
        self.export_to = tk.StringVar(value="2026-05-31")
        self.export_out = tk.StringVar(value=str(Path("exports/export_slice").resolve()))
        self.export_chat_id = tk.StringVar(value="")
        self.export_include_media = tk.BooleanVar(value=True)

        row1 = ttk.Frame(export_frame)
        row1.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(row1, text="从").pack(side=tk.LEFT)
        ttk.Entry(row1, textvariable=self.export_from, width=14).pack(
            side=tk.LEFT, padx=(4, 12)
        )
        ttk.Label(row1, text="到").pack(side=tk.LEFT)
        ttk.Entry(row1, textvariable=self.export_to, width=14).pack(
            side=tk.LEFT, padx=(4, 12)
        )
        ttk.Label(row1, text="群聊 ID（可空）").pack(side=tk.LEFT)
        ttk.Entry(row1, textvariable=self.export_chat_id, width=16).pack(
            side=tk.LEFT, padx=(4, 0)
        )

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
        log_frame = ttk.LabelFrame(root, text="运行日志", padding=10)
        log_frame.pack(fill=tk.BOTH, expand=True, **pad)
        self.log = scrolledtext.ScrolledText(
            log_frame,
            height=12,
            font=("Consolas", 10),
            state=tk.DISABLED,
            wrap=tk.WORD,
        )
        self.log.pack(fill=tk.BOTH, expand=True)

        self.status = ttk.Label(root, text="就绪", anchor=tk.W)
        self.status.pack(fill=tk.X, padx=10, pady=(0, 8))

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
            self.after(
                0,
                lambda: messagebox.showinfo(
                    "导入完成",
                    chats[0].message_count if chats else "已完成",
                ),
            )

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
        )


def should_launch_gui(argv: list[str] | None = None) -> bool:
    """True when the app should open the desktop UI instead of the CLI."""
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        return True
    if args == ["--gui"] or args == ["gui"]:
        return True
    return False
