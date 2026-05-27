"""Qt GUI for TeleArchive using QtWebEngine (PySide6)."""

from __future__ import annotations

import sys
import threading
import webbrowser
from datetime import datetime
from pathlib import Path

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
from PySide6.QtWebEngineWidgets import QWebEngineView

from telearchive import __version__
from telearchive.db import Database
from telearchive.export_chat import export_chat_range
from telearchive.export_dates import default_datetime_bounds, set_shortcut_range
from telearchive.html_board import clear_board_cache, render_range_to_cache
from telearchive.merge import ingest_paths
from telearchive.paths import (
    default_db_path,
    default_export_slice_dir,
    default_html_cache_dir,
)
from telearchive.updater import (
    ReleaseInfo,
    UpdateCheckResult,
    check_for_update,
    perform_in_app_update,
    should_notify_update,
)


class TeleArchiveWindow(QtWidgets.QMainWindow):
    update_result_ready = QtCore.Signal(object, bool)

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"TeleArchive Qt v{__version__}")
        self.resize(1100, 700)

        self.db_path = default_db_path().resolve()
        self.export_paths: list[Path] = []
        self.html_cache_dir = default_html_cache_dir().resolve()
        self._board_loaded = False
        self.update_result_ready.connect(self._on_update_result_ready)

        self._build_ui()
        QtCore.QTimer.singleShot(800, self._check_update_on_startup)

    # --- UI -----------------------------------------------------------------

    def _build_ui(self) -> None:
        central = QtWidgets.QWidget(self)
        self.setCentralWidget(central)

        layout = QtWidgets.QHBoxLayout(central)
        left = QtWidgets.QWidget()
        right = QtWidgets.QWidget()
        layout.addWidget(left, 3)
        layout.addWidget(right, 4)

        # Left column
        left_layout = QtWidgets.QVBoxLayout(left)

        title = QtWidgets.QLabel("TeleArchive")
        title.setFont(QtGui.QFont("Segoe UI", 18, QtGui.QFont.Bold))
        subtitle = QtWidgets.QLabel("Telegram 群聊归档与合并（Qt 版）")
        subtitle.setFont(QtGui.QFont("Segoe UI", 10))
        header_box = QtWidgets.QVBoxLayout()
        header_box.addWidget(title)
        header_box.addWidget(subtitle)
        head_widget = QtWidgets.QWidget()
        head_widget.setLayout(header_box)
        left_layout.addWidget(head_widget)

        # DB chooser
        db_box = QtWidgets.QGroupBox("数据库文件")
        db_layout = QtWidgets.QHBoxLayout(db_box)
        self.db_edit = QtWidgets.QLineEdit(str(self.db_path))
        db_btn = QtWidgets.QPushButton("浏览…")
        db_btn.clicked.connect(self._choose_db)
        db_layout.addWidget(self.db_edit)
        db_layout.addWidget(db_btn)
        left_layout.addWidget(db_box)

        # Export folders
        export_box = QtWidgets.QGroupBox("Telegram 导出文件夹")
        export_layout = QtWidgets.QVBoxLayout(export_box)
        self.export_list = QtWidgets.QListWidget()
        btn_row = QtWidgets.QHBoxLayout()
        btn_add = QtWidgets.QPushButton("添加文件夹…")
        btn_add.clicked.connect(self._add_export_folder)
        btn_clear = QtWidgets.QPushButton("清空列表")
        btn_clear.clicked.connect(self._clear_export_folders)
        btn_row.addWidget(btn_add)
        btn_row.addWidget(btn_clear)
        export_layout.addWidget(self.export_list)
        export_layout.addLayout(btn_row)
        left_layout.addWidget(export_box)

        # Actions
        action_row = QtWidgets.QHBoxLayout()
        self.btn_init = QtWidgets.QPushButton("初始化数据库")
        self.btn_init.clicked.connect(self._init_db)
        self.btn_ingest = QtWidgets.QPushButton("导入合并")
        self.btn_ingest.clicked.connect(self._run_ingest)
        self.btn_update = QtWidgets.QPushButton("检查更新")
        self.btn_update.clicked.connect(self._check_update_manual)
        action_row.addWidget(self.btn_init)
        action_row.addWidget(self.btn_ingest)
        action_row.addWidget(self.btn_update)
        left_layout.addLayout(action_row)

        # Export by time
        export_slice_box = QtWidgets.QGroupBox("按时间导出（Telegram JSON 格式）")
        export_slice_layout = QtWidgets.QVBoxLayout(export_slice_box)
        export_from_default, export_to_default = default_datetime_bounds()
        self.export_from = QtWidgets.QLineEdit(export_from_default)
        self.export_to = QtWidgets.QLineEdit(export_to_default)
        self.export_out = QtWidgets.QLineEdit(str(default_export_slice_dir().resolve()))

        time_row = QtWidgets.QHBoxLayout()
        time_row.addWidget(QtWidgets.QLabel("从"))
        time_row.addWidget(self.export_from)
        time_row.addWidget(QtWidgets.QLabel("到"))
        time_row.addWidget(self.export_to)
        export_slice_layout.addLayout(time_row)

        hint = QtWidgets.QLabel("时间格式 YYYY-MM-DD 或 YYYY-MM-DDTHH:MM:SS（UTC+8）")
        hint.setStyleSheet("color: #666666;")
        export_slice_layout.addWidget(hint)

        shortcut_row = QtWidgets.QHBoxLayout()
        for label, key in (
            ("今天", "today"),
            ("近三天", "3d"),
            ("近一周", "7d"),
            ("近一月", "30d"),
            ("全部消息", "all"),
        ):
            btn = QtWidgets.QPushButton(label)
            btn.clicked.connect(lambda _=False, k=key: self._set_export_shortcut(k))
            shortcut_row.addWidget(btn)
        export_slice_layout.addLayout(shortcut_row)

        out_row = QtWidgets.QHBoxLayout()
        out_row.addWidget(QtWidgets.QLabel("输出目录"))
        out_row.addWidget(self.export_out, 1)
        browse_export_btn = QtWidgets.QPushButton("浏览…")
        browse_export_btn.clicked.connect(self._browse_export_dir)
        out_row.addWidget(browse_export_btn)
        export_slice_layout.addLayout(out_row)

        export_btn_row = QtWidgets.QHBoxLayout()
        export_btn_row.addStretch(1)
        self.btn_export = QtWidgets.QPushButton("导出")
        self.btn_export.clicked.connect(self._run_export)
        export_btn_row.addWidget(self.btn_export)
        export_slice_layout.addLayout(export_btn_row)
        left_layout.addWidget(export_slice_box)

        # Log
        log_box = QtWidgets.QGroupBox("运行日志")
        log_layout = QtWidgets.QVBoxLayout(log_box)
        self.log = QtWidgets.QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(2000)
        log_layout.addWidget(self.log)
        left_layout.addWidget(log_box, 1)

        # Right: board
        right_layout = QtWidgets.QVBoxLayout(right)

        board_box = QtWidgets.QGroupBox("聊天看板（HTML 渲染，QtWebEngine）")
        board_layout = QtWidgets.QVBoxLayout(board_box)

        top_row = QtWidgets.QHBoxLayout()
        top_row.addWidget(QtWidgets.QLabel("从"))
        self.board_from = QtWidgets.QLineEdit()
        self.board_to = QtWidgets.QLineEdit()
        f_default, t_default = default_datetime_bounds()
        self.board_from.setText(f_default)
        self.board_to.setText(t_default)
        top_row.addWidget(self.board_from)
        top_row.addWidget(QtWidgets.QLabel("到"))
        top_row.addWidget(self.board_to)
        self.btn_board_refresh = QtWidgets.QPushButton("刷新预览")
        self.btn_board_refresh.clicked.connect(self._render_board)
        top_row.addWidget(self.btn_board_refresh)
        board_layout.addLayout(top_row)

        btn_row = QtWidgets.QHBoxLayout()
        for label, key in (
            ("今天", "today"),
            ("近三天", "3d"),
            ("近一周", "7d"),
            ("近一月", "30d"),
            ("全部消息", "all"),
        ):
            btn = QtWidgets.QPushButton(label)
            btn.clicked.connect(lambda _=False, k=key: self._set_board_shortcut(k))
            btn_row.addWidget(btn)
        board_layout.addLayout(btn_row)

        self.board_status = QtWidgets.QLabel("未加载")
        board_layout.addWidget(self.board_status)

        self.web = QWebEngineView()
        board_profile = QWebEngineProfile("TeleArchiveBoard", self.web)
        board_profile.setHttpCacheType(QWebEngineProfile.HttpCacheType.NoCache)
        self.web.setPage(QWebEnginePage(board_profile, self.web))
        board_layout.addWidget(self.web, 1)

        right_layout.addWidget(board_box, 1)

        self._log("Qt 看板已启用：使用 QtWebEngine 内嵌浏览器渲染 Telegram 原生 HTML。")

    # --- Helpers ------------------------------------------------------------

    def _log(self, text: str) -> None:
        now = datetime.now().strftime("%H:%M:%S")
        self.log.appendPlainText(f"[{now}] {text}")

    # --- DB / ingest --------------------------------------------------------

    def _choose_db(self) -> None:
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "选择数据库文件", str(self.db_path), "SQLite (*.db);;All Files (*.*)"
        )
        if path:
            self.db_path = Path(path)
            self.db_edit.setText(path)

    def _add_export_folder(self) -> None:
        path = QtWidgets.QFileDialog.getExistingDirectory(
            self, "选择 Telegram 导出文件夹"
        )
        if not path:
            return
        p = Path(path)
        if p in self.export_paths:
            return
        self.export_paths.append(p)
        self.export_list.addItem(str(p))
        self._log(f"已添加导出文件夹: {p}")

    def _clear_export_folders(self) -> None:
        self.export_paths.clear()
        self.export_list.clear()
        self._log("已清空导出文件夹列表。")

    def _init_db(self) -> None:
        self.db_path = Path(self.db_edit.text()).resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        if self.db_path.exists():
            QtWidgets.QMessageBox.information(
                self, "提示", f"数据库已存在，无需重复初始化：\n{self.db_path}"
            )
            self._log(f"数据库已存在，跳过初始化: {self.db_path}")
            return
        with Database(self.db_path) as db:
            db.migrate()
        self._log(f"数据库已初始化: {self.db_path}")

    def _run_ingest(self) -> None:
        if not self.export_paths:
            QtWidgets.QMessageBox.information(self, "提示", "请先添加 Telegram 导出文件夹。")
            return
        db_path = Path(self.db_edit.text()).resolve()
        if not db_path.parent.exists():
            db_path.parent.mkdir(parents=True, exist_ok=True)

        def worker() -> None:
            try:
                with Database(db_path) as db:
                    results = ingest_paths(db, self.export_paths)
            except Exception as exc:  # noqa: BLE001
                QtCore.QMetaObject.invokeMethod(
                    self,
                    "_show_error",
                    QtCore.Qt.QueuedConnection,
                    QtCore.Q_ARG(str, f"导入失败: {exc}"),
                )
                return

            lines = ["=== 导入完成 ==="]
            for path, stats in results:
                lines.append(f"{path}")
                lines.append(
                    f"  消息: {stats.messages_seen} 条，新增 {stats.messages_new}，更新 {stats.messages_updated}"
                )
                lines.append(
                    f"  媒体: 引用 {stats.media_refs}，存在 {stats.media_found}，缺失 {stats.media_missing}"
                )
            QtCore.QMetaObject.invokeMethod(
                self,
                "_append_log",
                QtCore.Qt.QueuedConnection,
                QtCore.Q_ARG(str, "\n".join(lines)),
            )
            QtCore.QMetaObject.invokeMethod(
                self,
                "_refresh_board_after_ingest",
                QtCore.Qt.QueuedConnection,
            )

        import threading as _t

        _t.Thread(target=worker, daemon=True).start()

    @QtCore.Slot(str)
    def _append_log(self, text: str) -> None:
        for line in text.splitlines():
            self._log(line)

    @QtCore.Slot(str)
    def _show_error(self, text: str) -> None:
        QtWidgets.QMessageBox.critical(self, "错误", text)

    @QtCore.Slot(str)
    def _show_info(self, text: str) -> None:
        QtWidgets.QMessageBox.information(self, "导出完成", text)

    def _browse_export_dir(self) -> None:
        base = Path(self.export_out.text().strip() or str(default_export_slice_dir())).resolve()
        base.mkdir(parents=True, exist_ok=True)
        path = QtWidgets.QFileDialog.getExistingDirectory(self, "选择导出目录", str(base))
        if path:
            self.export_out.setText(path)

    def _run_export(self) -> None:
        db_path = Path(self.db_edit.text()).resolve()
        if not db_path.is_file():
            QtWidgets.QMessageBox.warning(self, "提示", "数据库不存在，请先导入聊天记录。")
            return

        out_dir_text = self.export_out.text().strip()
        if not out_dir_text:
            QtWidgets.QMessageBox.warning(self, "提示", "请先选择输出目录。")
            return
        out_dir = Path(out_dir_text).resolve()
        out_dir.mkdir(parents=True, exist_ok=True)
        from_bound = self.export_from.text().strip()
        to_bound = self.export_to.text().strip()

        def worker() -> None:
            try:
                with Database(db_path) as db:
                    chats = db.list_chat_stats()
                    if not chats:
                        raise ValueError("数据库中没有聊天记录，请先导入。")
                    if len(chats) > 1:
                        raise ValueError("数据库中有多个群聊，请先在数据库中只保留目标群聊数据。")
                    chat_id = chats[0].chat_id
                    result = export_chat_range(
                        db,
                        out_dir,
                        chat_id,
                        from_bound=from_bound,
                        to_bound=to_bound,
                        include_media=True,
                    )
            except Exception as exc:  # noqa: BLE001
                QtCore.QMetaObject.invokeMethod(
                    self,
                    "_show_error",
                    QtCore.Qt.QueuedConnection,
                    QtCore.Q_ARG(str, f"导出失败: {exc}"),
                )
                return

            msg = (
                f"已导出 {result.message_count} 条消息\n"
                f"目录: {result.output_dir}\n"
                f"媒体: 复制 {result.media_copied}，缺失 {result.media_missing}"
            )
            QtCore.QMetaObject.invokeMethod(
                self,
                "_append_log",
                QtCore.Qt.QueuedConnection,
                QtCore.Q_ARG(
                    str,
                    "\n".join(
                        [
                            "=== 导出完成 ===",
                            f"群聊: {result.chat_name}",
                            f"目录: {result.output_dir}",
                            f"消息: {result.message_count} 条",
                            f"媒体: 复制 {result.media_copied}，缺失 {result.media_missing}",
                        ]
                    ),
                ),
            )
            QtCore.QMetaObject.invokeMethod(
                self,
                "_show_info",
                QtCore.Qt.QueuedConnection,
                QtCore.Q_ARG(str, msg),
            )

        import threading as _t

        _t.Thread(target=worker, daemon=True).start()

    # --- Board --------------------------------------------------------------

    def _set_export_shortcut(self, name: str) -> None:
        start, end = set_shortcut_range(name)
        self.export_from.setText(start)
        self.export_to.setText(end)

    def _set_board_shortcut(self, name: str) -> None:
        start, end = set_shortcut_range(name)
        self.board_from.setText(start)
        self.board_to.setText(end)
        self._render_board()

    @QtCore.Slot()
    def _refresh_board_after_ingest(self) -> None:
        if not self._board_loaded:
            return
        self._log("导入完成，正在从数据库重新渲染看板…")
        self._render_board()

    def _render_board(self) -> None:
        db_path = Path(self.db_edit.text()).resolve()
        if not db_path.is_file():
            QtWidgets.QMessageBox.warning(self, "提示", "数据库不存在，请先导入聊天记录。")
            return

        from_bound = self.board_from.text().strip()
        to_bound = self.board_to.text().strip()

        def worker() -> None:
            try:
                with Database(db_path) as db:
                    chats = db.list_chat_stats()
                    if not chats:
                        raise ValueError("数据库中没有聊天记录，请先导入。")
                    if len(chats) > 1:
                        raise ValueError("数据库中有多个群聊，请先在数据库中只保留目标群聊数据。")
                    chat_id = chats[0].chat_id
                    clear_board_cache(self.html_cache_dir, chat_id=chat_id)
                    result = render_range_to_cache(
                        db,
                        self.html_cache_dir,
                        chat_id,
                        from_bound,
                        to_bound,
                        force_refresh=True,
                    )
            except Exception as exc:  # noqa: BLE001
                QtCore.QMetaObject.invokeMethod(
                    self,
                    "_show_error",
                    QtCore.Qt.QueuedConnection,
                    QtCore.Q_ARG(str, str(exc)),
                )
                return

            QtCore.QMetaObject.invokeMethod(
                self,
                "_load_board",
                QtCore.Qt.QueuedConnection,
                QtCore.Q_ARG(str, str(result.html_path)),
                QtCore.Q_ARG(str, result.chat_name),
                QtCore.Q_ARG(int, result.message_count),
            )

        # simple thread via Python threading to avoid blocking UI
        import threading as _t

        _t.Thread(target=worker, daemon=True).start()

    @QtCore.Slot(str, str, int)
    def _load_board(self, html_path: str, chat_name: str, count: int) -> None:
        path = Path(html_path).resolve()
        self._board_loaded = True
        self.board_status.setText(
            f"{chat_name} | {count} 条 | {self.board_from.text()} ~ {self.board_to.text()}"
        )
        self.web.load(QtCore.QUrl.fromLocalFile(str(path)))
        self._log(f"看板已加载: {path}（TG 导出 HTML 文件夹）")

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        clear_board_cache(self.html_cache_dir)
        self._board_loaded = False
        self.web.setUrl(QtCore.QUrl("about:blank"))
        super().closeEvent(event)

    # --- Update -------------------------------------------------------------

    def _check_update_on_startup(self) -> None:
        def worker() -> None:
            result = check_for_update()
            self.update_result_ready.emit(result, True)

        threading.Thread(target=worker, daemon=True).start()

    def _check_update_manual(self) -> None:
        self._log("正在检查更新…")

        def worker() -> None:
            result = check_for_update()
            self.update_result_ready.emit(result, False)

        threading.Thread(target=worker, daemon=True).start()

    @QtCore.Slot(object, bool)
    def _on_update_result_ready(self, result: object, quiet: bool) -> None:
        if not isinstance(result, UpdateCheckResult):
            return
        if quiet and not should_notify_update(result):
            return
        if result.error:
            if not quiet:
                QtWidgets.QMessageBox.warning(self, "检查更新", result.error)
            self._log(f"检查更新失败: {result.error}")
            return
        if not result.has_update:
            if not quiet:
                QtWidgets.QMessageBox.information(
                    self,
                    "检查更新",
                    f"当前已是最新版本（v{result.current_version}）。",
                )
            self._log(f"当前已是最新版本: v{result.current_version}")
            return
        if result.latest:
            self._present_update(result.latest, result.current_version, quiet=quiet)

    def _present_update(self, release: ReleaseInfo, current_version: str, *, quiet: bool) -> None:
        if quiet:
            self._log(f"发现新版本 v{release.version}。")
        box = QtWidgets.QMessageBox(self)
        box.setIcon(QtWidgets.QMessageBox.Information)
        box.setWindowTitle("发现新版本")
        box.setText(f"当前版本: v{current_version}\n最新版本: v{release.version}")
        box.setInformativeText("可选择立即更新，或前往 Release 页面下载。")
        notes = release.notes.strip() or "（无更新说明）"
        box.setDetailedText(notes[:4000])
        btn_update = box.addButton("立即更新", QtWidgets.QMessageBox.AcceptRole)
        btn_open = box.addButton("前往下载", QtWidgets.QMessageBox.ActionRole)
        box.addButton("稍后", QtWidgets.QMessageBox.RejectRole)
        box.exec()
        clicked = box.clickedButton()
        if clicked == btn_update:
            self._update_now(release)
            return
        if clicked == btn_open:
            webbrowser.open(release.download_url or release.url)

    def _update_now(self, release: ReleaseInfo) -> None:
        self._log("正在下载并更新…")

        def worker() -> None:
            try:
                perform_in_app_update(release)
            except RuntimeError as exc:
                QtCore.QMetaObject.invokeMethod(
                    self,
                    "_show_error",
                    QtCore.Qt.QueuedConnection,
                    QtCore.Q_ARG(str, str(exc)),
                )
                return
            except Exception as exc:  # noqa: BLE001
                QtCore.QMetaObject.invokeMethod(
                    self,
                    "_show_error",
                    QtCore.Qt.QueuedConnection,
                    QtCore.Q_ARG(str, f"立即更新失败: {exc}"),
                )
                return

            QtCore.QMetaObject.invokeMethod(
                self,
                "_append_log",
                QtCore.Qt.QueuedConnection,
                QtCore.Q_ARG(str, "更新包已验证，应用即将重启…"),
            )
            QtCore.QMetaObject.invokeMethod(
                self,
                "_shutdown_for_update",
                QtCore.Qt.QueuedConnection,
            )

        threading.Thread(target=worker, daemon=True).start()

    @QtCore.Slot()
    def _shutdown_for_update(self) -> None:
        self._log("正在关闭界面以完成更新…")
        self.web.setUrl(QtCore.QUrl("about:blank"))
        QtWidgets.QApplication.processEvents()
        QtCore.QTimer.singleShot(500, QtWidgets.QApplication.instance().quit)


def launch_qt_gui() -> None:
    QtCore.QCoreApplication.setAttribute(QtCore.Qt.AA_ShareOpenGLContexts)
    app = QtWidgets.QApplication(sys.argv)
    window = TeleArchiveWindow()
    window.show()
    sys.exit(app.exec())

