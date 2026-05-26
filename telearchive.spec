# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec: pyinstaller telearchive.spec"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

import telearchive

block_cipher = None
_tg_assets = Path(telearchive.__file__).resolve().parent / "assets" / "tg_export"

hiddenimports = (
    collect_submodules("rich")
    + collect_submodules("typer")
    + collect_submodules("webview")
    + [
    "click",
    "shellingham",
    "sqlite3",
    "tkinter",
    "telearchive",
    "telearchive.cli",
    "telearchive.gui",
    "telearchive.db",
    "telearchive.merge",
    "telearchive.parser",
    "telearchive.media",
    "telearchive.coverage",
    "telearchive.settings",
    "telearchive.paths",
    "telearchive.updater",
    "telearchive.update_dialog",
    "telearchive.notify",
    "telearchive.export_dates",
    "telearchive.export_chat",
    "telearchive.html_board",
    "telearchive.board_browser",
]
)

a = Analysis(
    ["telearchive/__main__.py"],
    pathex=[],
    binaries=[],
    datas=collect_data_files("telearchive")
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
    # Extract onefile runtime payload next to the exe, instead of system temp.
    # This avoids "Failed to load Python DLL" on some Windows setups where TEMP is restricted.
    runtime_tmpdir=".",
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
