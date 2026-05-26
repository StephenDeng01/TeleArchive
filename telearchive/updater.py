"""Check for new releases and optionally perform in-app update on Windows."""

from __future__ import annotations

import json
import hashlib
import os
import subprocess
import tempfile
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from telearchive import __version__
from telearchive.settings import get_dismissed_update_version, set_dismissed_update_version

GITHUB_OWNER = "StephenDeng01"
GITHUB_REPO = "TeleArchive"
RELEASES_PAGE = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases"
LATEST_RELEASE_API = (
    f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
)
RELEASES_LIST_API = (
    f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases?per_page=10"
)
VERSION_MANIFEST_URL = (
    f"https://raw.githubusercontent.com/{GITHUB_OWNER}/{GITHUB_REPO}/main/version.json"
)
USER_AGENT = f"TeleArchive/{__version__}"


@dataclass(frozen=True)
class ReleaseInfo:
    version: str
    tag: str
    title: str
    url: str
    notes: str
    download_url: str | None
    sha256: str | None = None


@dataclass(frozen=True)
class UpdateCheckResult:
    current_version: str
    latest: ReleaseInfo | None
    error: str | None = None

    @property
    def has_update(self) -> bool:
        return self.latest is not None and compare_versions(
            self.latest.version, self.current_version
        ) > 0

    @property
    def is_dismissed(self) -> bool:
        if not self.latest:
            return False
        dismissed = get_dismissed_update_version()
        return dismissed == self.latest.version


def normalize_version(tag: str) -> str:
    match = re.match(r"^v?(\d+(?:\.\d+)*)", tag.strip(), re.IGNORECASE)
    return match.group(1) if match else tag.lstrip("vV")


def compare_versions(left: str, right: str) -> int:
    """Return 1 if left > right, -1 if left < right, 0 if equal."""

    def parts(value: str) -> list[int]:
        nums = []
        for segment in normalize_version(value).split("."):
            digits = "".join(ch for ch in segment if ch.isdigit())
            nums.append(int(digits) if digits else 0)
        return (nums + [0, 0, 0])[:3]

    a, b = parts(left), parts(right)
    if a > b:
        return 1
    if a < b:
        return -1
    return 0


def _http_get_json(url: str, *, timeout: float) -> Any:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Cache-Control": "no-cache",
            "User-Agent": USER_AGENT,
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _http_get_text(url: str, *, timeout: float) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "text/plain,*/*",
            "Cache-Control": "no-cache",
            "User-Agent": USER_AGENT,
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def _try_fetch_sha256_sidecar(download_url: str, *, timeout: float) -> str | None:
    """
    Try to fetch an adjacent .sha256 file from GitHub Releases.

    Expected contents: either a bare hex digest, or common formats like:
    - SHA256: <hex>
    - <hex>  TeleArchive.exe
    """
    candidates = []
    if download_url.endswith(".exe"):
        candidates.append(download_url + ".sha256")
        candidates.append(download_url.removesuffix(".exe") + ".exe.sha256")
    else:
        candidates.append(download_url + ".sha256")

    ts = int(time.time())
    for base in candidates:
        url = f"{base}?ts={ts}"
        try:
            raw = _http_get_text(url, timeout=timeout).strip()
        except (urllib.error.URLError, TimeoutError, ValueError, urllib.error.HTTPError):
            continue
        raw = raw.replace("\r\n", "\n")
        first_line = raw.split("\n", 1)[0].strip()
        # extract first 64-hex sequence if present
        m = re.search(r"\b([0-9a-fA-F]{64})\b", first_line)
        if m:
            return m.group(1).lower()
    return None


def _normalize_sha256(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    sha = value.strip().lower()
    if re.fullmatch(r"[0-9a-f]{64}", sha):
        return sha
    return None


def _sidecar_sha256_for_release(release: ReleaseInfo, *, timeout: float) -> str | None:
    if release.download_url:
        sha = _try_fetch_sha256_sidecar(release.download_url, timeout=timeout)
        if sha:
            return sha
    if release.tag:
        return _try_fetch_sha256_sidecar(
            f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases/download/{release.tag}/TeleArchive.exe",
            timeout=timeout,
        )
    return None


def resolve_release_sha256(release: ReleaseInfo, *, timeout: float = 20.0) -> ReleaseInfo:
    """Prefer Release .sha256 sidecar over manifest (manifest may be stale after re-runs)."""
    sidecar = _sidecar_sha256_for_release(release, timeout=timeout)
    if sidecar:
        return replace(release, sha256=sidecar)
    return release


def _parse_github_http_error(exc: urllib.error.HTTPError) -> str:
    message = ""
    try:
        raw = exc.read().decode("utf-8", errors="replace")
        payload = json.loads(raw)
        if isinstance(payload, dict):
            message = str(payload.get("message") or "")
    except (json.JSONDecodeError, OSError):
        pass

    if exc.code == 403:
        hint = message or "未认证请求频率受限或网络受限"
        return (
            f"GitHub API 访问受限 (403): {hint}。"
            f"请稍后重试，或在浏览器打开：{RELEASES_PAGE}"
        )
    if exc.code == 404:
        hint = message or "仓库未公开、尚无 Release，或 API 不可达"
        return (
            f"未找到 Release (404): {hint}。"
            f"可手动查看：{RELEASES_PAGE}"
        )
    if message:
        return f"GitHub API 错误 ({exc.code}): {message}"
    return f"GitHub API 错误 ({exc.code})，请稍后重试或打开 {RELEASES_PAGE}"


def _release_from_payload(payload: dict[str, Any]) -> ReleaseInfo:
    tag = str(payload.get("tag_name") or payload.get("tag") or "")
    version = normalize_version(str(payload.get("version") or tag))
    notes = str(payload.get("body") or payload.get("notes") or "").strip()
    url = str(
        payload.get("html_url")
        or payload.get("release_url")
        or RELEASES_PAGE
    )
    title = str(payload.get("name") or payload.get("title") or f"TeleArchive {tag}")

    download_url = payload.get("download_url")
    if isinstance(download_url, str) and download_url:
        download_url = download_url
    else:
        download_url = None
        for asset in payload.get("assets") or []:
            if not isinstance(asset, dict):
                continue
            name = str(asset.get("name") or "")
            if name.lower() in ("telearchive.exe", "telearchive"):
                download_url = str(asset.get("browser_download_url") or "") or None
                break

    manifest_sha = _normalize_sha256(payload.get("sha256"))
    sidecar_sha: str | None = None
    if isinstance(download_url, str) and download_url:
        sidecar_sha = _try_fetch_sha256_sidecar(download_url, timeout=8.0)
    if not sidecar_sha and tag:
        sidecar_sha = _try_fetch_sha256_sidecar(
            f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases/download/{tag}/TeleArchive.exe",
            timeout=8.0,
        )
    sha256 = sidecar_sha or manifest_sha

    if not version:
        raise ValueError("Release metadata incomplete")

    return ReleaseInfo(
        version=version,
        tag=tag or f"v{version}",
        title=title,
        url=url,
        notes=notes,
        download_url=download_url,
        sha256=sha256,
    )


def fetch_latest_from_manifest(timeout: float = 8.0) -> ReleaseInfo:
    # raw.githubusercontent.com is cached; add cache-busting query param
    url = f"{VERSION_MANIFEST_URL}?ts={int(time.time())}"
    payload = _http_get_json(url, timeout=timeout)
    if not isinstance(payload, dict):
        raise ValueError("version.json 格式无效")
    return _release_from_payload(payload)


def fetch_latest_from_api(timeout: float = 8.0) -> ReleaseInfo:
    try:
        payload = _http_get_json(LATEST_RELEASE_API, timeout=timeout)
        if isinstance(payload, dict):
            return _release_from_payload(payload)
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            raise
    payload = _http_get_json(RELEASES_LIST_API, timeout=timeout)
    if not isinstance(payload, list):
        raise ValueError("Unexpected GitHub releases list")
    for item in payload:
        if not isinstance(item, dict):
            continue
        if item.get("draft"):
            continue
        return _release_from_payload(item)
    raise ValueError("GitHub 上尚无可用 Release")


def fetch_latest_release(timeout: float = 8.0) -> ReleaseInfo:
    """Try version.json first (CDN), then GitHub API."""
    manifest_error: str | None = None
    try:
        return fetch_latest_from_manifest(timeout=timeout)
    except urllib.error.HTTPError as exc:
        manifest_error = _parse_github_http_error(exc)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError) as exc:
        manifest_error = str(exc)

    try:
        return fetch_latest_from_api(timeout=timeout)
    except urllib.error.HTTPError:
        raise
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError) as exc:
        if manifest_error:
            raise ValueError(f"{manifest_error}; API: {exc}") from exc
        raise


def check_for_update(timeout: float = 8.0) -> UpdateCheckResult:
    current = __version__
    try:
        latest = fetch_latest_release(timeout=timeout)
    except urllib.error.HTTPError as exc:
        detail = str(exc.reason) if exc.reason else _parse_github_http_error(exc)
        return UpdateCheckResult(
            current_version=current,
            latest=None,
            error=detail,
        )
    except urllib.error.URLError as exc:
        return UpdateCheckResult(
            current_version=current,
            latest=None,
            error=f"网络不可用: {exc.reason}。可手动打开 {RELEASES_PAGE}",
        )
    except (TimeoutError, json.JSONDecodeError, ValueError) as exc:
        return UpdateCheckResult(
            current_version=current,
            latest=None,
            error=f"{exc}。可手动打开 {RELEASES_PAGE}",
        )

    if compare_versions(latest.version, current) <= 0:
        return UpdateCheckResult(current_version=current, latest=None)

    latest = resolve_release_sha256(latest, timeout=timeout)
    return UpdateCheckResult(current_version=current, latest=latest)


def dismiss_update_reminder(version: str) -> None:
    set_dismissed_update_version(version)


def should_notify_update(result: UpdateCheckResult) -> bool:
    return result.has_update and not result.is_dismissed


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _download_file(url: str, target: Path, *, timeout: float = 30.0) -> None:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/octet-stream",
            "User-Agent": USER_AGENT,
        },
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        with target.open("wb") as out:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)


def perform_in_app_update(release: ReleaseInfo) -> None:
    """
    Download, verify SHA256, replace executable, and relaunch (Windows only).

    This function is intended for frozen executable distribution.
    """
    if os.name != "nt":
        raise RuntimeError("仅 Windows 桌面版支持“立即更新”。")
    if not getattr(sys, "frozen", False):
        raise RuntimeError("当前为源码运行模式，无法自替换可执行文件。")
    if not release.download_url:
        raise RuntimeError("该版本未提供下载地址。")
    release = resolve_release_sha256(release, timeout=30.0)
    if not release.sha256:
        raise RuntimeError(
            "该版本未提供 sha256，已阻止自动更新以保证安全。"
            "请稍后重试，或从 Releases 页面手动下载安装。"
        )

    current_exe = Path(sys.executable).resolve()
    staging_dir = Path(tempfile.gettempdir()) / "telearchive-update"
    new_exe = staging_dir / f"TeleArchive-{release.version}.exe"
    _download_file(release.download_url, new_exe)

    actual_hash = _sha256_file(new_exe)
    if actual_hash != release.sha256.lower():
        raise RuntimeError(
            "更新包 SHA256 校验失败，已取消更新。"
            f"\n期望: {release.sha256}\n实际: {actual_hash}"
        )

    updater_bat = staging_dir / "apply_update.bat"
    updater_bat.write_text(
        _build_windows_updater_script(
            current_exe=current_exe,
            new_exe=new_exe,
        ),
        encoding="utf-8",
    )

    # Detached updater process: wait current app exit, replace exe, relaunch.
    CREATE_NO_WINDOW = 0x08000000
    DETACHED_PROCESS = 0x00000008
    subprocess.Popen(
        ["cmd", "/c", str(updater_bat)],
        creationflags=CREATE_NO_WINDOW | DETACHED_PROCESS,
        close_fds=True,
        cwd=str(staging_dir),
    )


def _build_windows_updater_script(*, current_exe: Path, new_exe: Path) -> str:
    exe = str(current_exe)
    bak = str(current_exe.with_suffix(current_exe.suffix + ".old"))
    newf = str(new_exe)
    exedir = str(current_exe.parent)
    log = str(Path(tempfile.gettempdir()) / "telearchive-update" / "update.log")
    return f"""@echo off
setlocal enabledelayedexpansion
set "TARGET={exe}"
set "BACKUP={bak}"
set "NEWFILE={newf}"
set "EXEDIR={exedir}"
set "LOGFILE={log}"
set /a ATTEMPT=0

echo [%date% %time%] updater started >> "%LOGFILE%"

:wait_and_replace
timeout /t 1 /nobreak >nul
set /a ATTEMPT+=1

if exist "%BACKUP%" del /f /q "%BACKUP%" >nul 2>nul
if exist "%TARGET%" move /Y "%TARGET%" "%BACKUP%" >nul 2>nul
if exist "%TARGET%" (
  if !ATTEMPT! lss 120 goto wait_and_replace
  echo [%date% %time%] replace timeout, restoring backup >> "%LOGFILE%"
  goto fallback_launch_old
)

move /Y "%NEWFILE%" "%TARGET%" >nul 2>nul
if exist "%TARGET%" (
  cd /d "%EXEDIR%"
  powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -LiteralPath '%TARGET%' -WorkingDirectory '%EXEDIR%'" >nul 2>nul
  if errorlevel 1 (
    start "" "%TARGET%"
  )
  echo [%date% %time%] relaunched %TARGET% >> "%LOGFILE%"
  if exist "%BACKUP%" del /f /q "%BACKUP%" >nul 2>nul
  del /f /q "%~f0" >nul 2>nul
  exit /b 0
)

:fallback_launch_old
if exist "%BACKUP%" (
  cd /d "%EXEDIR%"
  powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -LiteralPath '%BACKUP%' -WorkingDirectory '%EXEDIR%'" >nul 2>nul
  if errorlevel 1 start "" "%BACKUP%"
)
del /f /q "%~f0" >nul 2>nul
exit /b 1
"""
