"""Qt GUI for TeleArchive using QtWebEngine (PySide6)."""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtWebEngineWidgets import QWebEngineView

from telearchive import __version__
from telearchive.db import Database
from telearchive.export_chat import export_chat_range
from telearchive.export_dates import default_datetime_bounds, set_shortcut_range
from telearchive.html_board import (
    BoardRenderResult,
    render_range_to_cache,
    warmup_all_messages_cache,
)
from telearchive.merge import ingest_paths
from telearchive.paths import (
    default_db_path,
    default_export_slice_dir,
    default_html_cache_dir,
)


class TeleArchiveWindow(QtWidgets.QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"TeleArchive Qt v{__version__}")
        self.resize(1100, 700)

        self.db_path = default_db_path().resolve()
        self.export_paths: list[Path] = []
        self.html_cache_dir = default_html_cache_dir().resolve()

        self._build_ui()

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
        self.btn_export = QtWidgets.QPushButton("按时间导出")
        self.btn_export.clicked.connect(self._run_export)
        action_row.addWidget(self.btn_init)
        action_row.addWidget(self.btn_ingest)
        action_row.addWidget(self.btn_export)
        left_layout.addLayout(action_row)

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

        threading = QtCore.QThread
        t = threading(target=worker)  # type: ignore[call-arg]
        t.setObjectName("ingest-thread")

    @QtCore.Slot(str)
    def _append_log(self, text: str) -> None:
        for line in text.splitlines():
            self._log(line)

    @QtCore.Slot(str)
    def _show_error(self, text: str) -> None:
        QtWidgets.QMessageBox.critical(self, "错误", text)

    # --- Board --------------------------------------------------------------

    def _set_board_shortcut(self, name: str) -> None:
        start, end = set_shortcut_range(name)
        self.board_from.setText(start)
        self.board_to.setText(end)
        self._render_board()

    def _render_board(self) -> None:
        db_path = Path(self.db_edit.text()).resolve()
        if not db_path.is_file():
            QtWidgets.QMessageBox.warning(self, "提示", "数据库不存在，请先导入聊天记录。")
            return

        def worker() -> None:
            try:
                with Database(db_path) as db:
                    chats = db.list_chat_stats()
                    if not chats:
                        raise ValueError("数据库中没有聊天记录，请先导入。")
                    if len(chats) > 1:
                        raise ValueError("数据库中有多个群聊，请使用 Tk 版填写群聊 ID。")
                    chat_id = chats[0].chat_id
                    result = render_range_to_cache(
                        db,
                        self.html_cache_dir,
                        chat_id,
                        self.board_from.text().strip(),
                        self.board_to.text().strip(),
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
        self.board_status.setText(
            f"{chat_name} | {count} 条 | {self.board_from.text()} ~ {self.board_to.text()}"
        )
        self.web.load(QtCore.QUrl.fromLocalFile(str(path)))
        self._log(f"看板已加载: {path}")


def launch_qt_gui() -> None:
    app = QtWidgets.QApplication(sys.argv)
    window = TeleArchiveWindow()
    window.show()
    sys.exit(app.exec())

