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


_RUNTIME_RESOLVED = False
_RUNTIME_PATH: Path | None = None


def resolve_portable_runtime_dir() -> Path | None:
    """
    Find a folder containing ``msedgewebview2.exe`` beside the app or cwd.

    Supports the official zip layout (``WebView2Runtime/`` next to the exe)
    and shallow mis-nesting (e.g. user only moved the exe).
    """
    global _RUNTIME_RESOLVED, _RUNTIME_PATH
    if _RUNTIME_RESOLVED:
        return _RUNTIME_PATH

    roots: list[Path] = []
    exe_parent = app_install_dir()
    roots.append(exe_parent)
    # Same folder as argv[0] when frozen (e.g. shortcut oddities)
    try:
        argv0 = Path(sys.argv[0]).resolve()
        if argv0.is_file():
            roots.append(argv0.parent)
    except OSError:
        pass
    try:
        roots.append(Path.cwd().resolve())
    except OSError:
        pass

    seen: set[Path] = set()
    candidates: list[Path] = []
    for root in roots:
        root = root.resolve()
        if root in seen:
            continue
        seen.add(root)
        for name in ("WebView2Runtime", "WebView2", "webview2runtime"):
            candidates.append(root / name)
        if root.is_dir():
            for child in root.iterdir():
                if child.is_dir():
                    candidates.append(child)

    found: Path | None = None
    for folder in candidates:
        try:
            exe = folder / "msedgewebview2.exe"
        except OSError:
            continue
        if exe.is_file():
            found = folder.resolve()
            break

    _RUNTIME_RESOLVED = True
    _RUNTIME_PATH = found
    return found


def portable_runtime_dir() -> Path:
    resolved = resolve_portable_runtime_dir()
    if resolved is not None:
        return resolved
    return app_install_dir() / "WebView2Runtime"


def portable_user_data_dir() -> Path:
    return app_install_dir() / "WebView2Data"


def is_runtime_ready(runtime_dir: Path | None = None) -> bool:
    if runtime_dir is not None:
        return (runtime_dir / "msedgewebview2.exe").is_file()
    return resolve_portable_runtime_dir() is not None


def configure_portable_webview2() -> bool:
    """
    Point WebView2 at the portable Fixed Runtime folder under the app directory.

    Must be called before ``webview.start()`` / first WebView2 use.
  """
    if sys.platform != "win32":
        return False
    runtime = resolve_portable_runtime_dir()
    if runtime is None or not (runtime / "msedgewebview2.exe").is_file():
        return False
    data_dir = portable_user_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    os.environ["WEBVIEW2_BROWSER_EXECUTABLE_FOLDER"] = str(runtime.resolve())
    os.environ["WEBVIEW2_USER_DATA_FOLDER"] = str(data_dir.resolve())
    return True


def runtime_status_message() -> str:
    if sys.platform != "win32":
        return "仅 Windows 支持内嵌 WebView2。"
    runtime = resolve_portable_runtime_dir()
    if runtime is not None:
        return f"便携 WebView2 已就绪: {runtime}"
    return (
        f"未找到便携 WebView2（期望目录: {app_install_dir() / 'WebView2Runtime'}）。\n"
        "请使用完整安装包（含 WebView2Runtime 文件夹），"
        "或在应用内执行「安装便携 WebView2」。"
    )


def invalidate_runtime_cache() -> None:
    global _RUNTIME_RESOLVED, _RUNTIME_PATH
    _RUNTIME_RESOLVED = False
    _RUNTIME_PATH = None


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
    invalidate_runtime_cache()
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
