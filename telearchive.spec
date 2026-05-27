# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec: pyinstaller telearchive.spec"""

from pathlib import Path

from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
)

import telearchive

block_cipher = None
_assets_dir = Path(telearchive.__file__).resolve().parent / "assets"
_app_icon = _assets_dir / "logo.ico"
_tg_assets = _assets_dir / "tg_export"

hiddenimports = (
    collect_submodules("rich")
    + collect_submodules("typer")
    + collect_submodules("PySide6")
    + collect_submodules("PySide6.QtWebEngineCore")
    + collect_submodules("PySide6.QtWebEngineWidgets")
    + [
    "click",
    "shellingham",
    "sqlite3",
    "telearchive",
    "telearchive.cli",
    "telearchive.gui_qt",
    "telearchive.db",
    "telearchive.merge",
    "telearchive.parser",
    "telearchive.media",
    "telearchive.coverage",
    "telearchive.settings",
    "telearchive.paths",
    "telearchive.updater",
    "telearchive.update_dialog",
    "telearchive.frozen_runtime",
    "telearchive.notify",
    "telearchive.export_dates",
    "telearchive.export_chat",
    "telearchive.html_board",
]
)

_pyside6_datas = collect_data_files("PySide6", include_py_files=False)
_pyside6_binaries = collect_dynamic_libs("PySide6")

a = Analysis(
    ["telearchive/__main__.py"],
    pathex=[],
    binaries=_pyside6_binaries,
    datas=collect_data_files("telearchive")
    + _pyside6_datas
    + [
        (str(_tg_assets / "css"), "telearchive/assets/tg_export/css"),
        (str(_tg_assets / "js"), "telearchive/assets/tg_export/js"),
        (str(_tg_assets / "images"), "telearchive/assets/tg_export/images"),
    ],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="TeleArchive",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    # Extract runtime payload under %LOCALAPPDATA% so exe self-update does not
    # fight with _MEI folders next to TeleArchive.exe.
    runtime_tmpdir=r"%LOCALAPPDATA%\TeleArchive\_pyi",
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(_app_icon) if _app_icon.is_file() else None,
)
