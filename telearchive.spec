# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec: pyinstaller telearchive.spec"""

from PyInstaller.utils.hooks import collect_submodules

block_cipher = None

hiddenimports = (
    collect_submodules("rich")
    + collect_submodules("typer")
    + collect_submodules("tkinterweb")
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
]
)

a = Analysis(
    ["telearchive/__main__.py"],
    pathex=[],
    binaries=[],
    datas=[],
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
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
