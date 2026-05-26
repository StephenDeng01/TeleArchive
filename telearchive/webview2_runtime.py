"""Portable WebView2 Fixed Runtime next to the app (no system-wide install)."""

from __future__ import annotations

import os
import shutil
import sys
import zipfile
from collections.abc import Callable
from pathlib import Path
from urllib.request import urlretrieve

# Pinned Fixed Version (x64) via community NuGet mirror of Microsoft's runtime.
FIXED_RUNTIME_VERSION = "148.0.3967.83"
NUGET_URL = (
    "https://api.nuget.org/v3-flatcontainer/webview2.runtime.x64/"
    f"{FIXED_RUNTIME_VERSION}/webview2.runtime.x64.{FIXED_RUNTIME_VERSION}.nupkg"
)


def app_install_dir() -> Path:
    """Directory containing TeleArchive.exe (or project root in dev)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def portable_runtime_dir() -> Path:
    return app_install_dir() / "WebView2Runtime"


def portable_user_data_dir() -> Path:
    return app_install_dir() / "WebView2Data"


def is_runtime_ready(runtime_dir: Path | None = None) -> bool:
    folder = runtime_dir or portable_runtime_dir()
    return (folder / "msedgewebview2.exe").is_file()


def configure_portable_webview2() -> bool:
    """
    Point WebView2 at the portable Fixed Runtime folder under the app directory.

    Must be called before ``webview.start()`` / first WebView2 use.
  """
    if sys.platform != "win32":
        return False
    runtime = portable_runtime_dir()
    if not is_runtime_ready(runtime):
        return False
    data_dir = portable_user_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    os.environ["WEBVIEW2_BROWSER_EXECUTABLE_FOLDER"] = str(runtime.resolve())
    os.environ["WEBVIEW2_USER_DATA_FOLDER"] = str(data_dir.resolve())
    return True


def runtime_status_message() -> str:
    if sys.platform != "win32":
        return "仅 Windows 支持内嵌 WebView2。"
    runtime = portable_runtime_dir()
    if is_runtime_ready(runtime):
        return f"便携 WebView2 已就绪: {runtime}"
    return (
        f"未找到便携 WebView2（{runtime}）。\n"
        "请使用完整安装包（含 WebView2Runtime 文件夹），"
        "或在应用内执行「安装便携 WebView2」。"
    )


def bootstrap_portable_runtime(
    *,
    progress: Callable[[str], None] | None = None,
) -> Path:
    """
    Download and extract Fixed Version WebView2 into ``WebView2Runtime/`` under the app.

    Files stay beside TeleArchive.exe only; nothing is written to Program Files.
    """
    if sys.platform != "win32":
        raise RuntimeError("仅 Windows 支持便携 WebView2。")

    def log(msg: str) -> None:
        if progress:
            progress(msg)

    target = portable_runtime_dir()
    if is_runtime_ready(target):
        configure_portable_webview2()
        return target

    install_root = app_install_dir()
    install_root.mkdir(parents=True, exist_ok=True)
    staging = install_root / "_webview2_staging"
    if staging.exists():
        shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True, exist_ok=True)

    zip_path = staging / "webview2.nupkg.zip"
    log(f"正在下载 WebView2 {FIXED_RUNTIME_VERSION}…")
    urlretrieve(NUGET_URL, zip_path)  # noqa: S310

    log("正在解压…")
    extract_root = staging / "pkg"
    with zipfile.ZipFile(zip_path) as archive:
        archive.extractall(extract_root)

    runtime_exe: Path | None = None
    for candidate in extract_root.rglob("msedgewebview2.exe"):
        runtime_exe = candidate
        break
    if runtime_exe is None:
        raise RuntimeError("NuGet 包中未找到 msedgewebview2.exe")

    native = runtime_exe.parent
    if target.exists():
        shutil.rmtree(target, ignore_errors=True)
    shutil.copytree(native, target)
    (target / "telearchive-webview2-version.txt").write_text(
        FIXED_RUNTIME_VERSION, encoding="ascii"
    )

    shutil.rmtree(staging, ignore_errors=True)
    configure_portable_webview2()
    log(f"便携 WebView2 已安装到: {target}")
    return target


def ensure_portable_runtime(
    *,
    progress: Callable[[str], None] | None = None,
    allow_download: bool = True,
) -> bool:
    if configure_portable_webview2():
        return True
    if not allow_download:
        return False
    try:
        bootstrap_portable_runtime(progress=progress)
    except OSError as exc:
        if progress:
            progress(f"便携 WebView2 安装失败: {exc}")
        return False
    return configure_portable_webview2()
