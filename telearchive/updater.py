"""Check for new releases on GitHub (optional, user-initiated or reminder)."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
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
            "User-Agent": USER_AGENT,
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


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

    if not version:
        raise ValueError("Release metadata incomplete")

    return ReleaseInfo(
        version=version,
        tag=tag or f"v{version}",
        title=title,
        url=url,
        notes=notes,
        download_url=download_url,
    )


def fetch_latest_from_manifest(timeout: float = 8.0) -> ReleaseInfo:
    payload = _http_get_json(VERSION_MANIFEST_URL, timeout=timeout)
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

    return UpdateCheckResult(current_version=current, latest=latest)


def dismiss_update_reminder(version: str) -> None:
    set_dismissed_update_version(version)


def should_notify_update(result: UpdateCheckResult) -> bool:
    return result.has_update and not result.is_dismissed
