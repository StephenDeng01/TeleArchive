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
LATEST_RELEASE_API = (
    f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
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


def fetch_latest_release(timeout: float = 8.0) -> ReleaseInfo:
    request = urllib.request.Request(
        LATEST_RELEASE_API,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": USER_AGENT,
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))

    if not isinstance(payload, dict):
        raise ValueError("Unexpected GitHub API response")

    tag = str(payload.get("tag_name") or "")
    version = normalize_version(tag)
    notes = str(payload.get("body") or "").strip()
    url = str(payload.get("html_url") or "")
    title = str(payload.get("name") or f"TeleArchive {tag}")

    download_url = None
    for asset in payload.get("assets") or []:
        if not isinstance(asset, dict):
            continue
        name = str(asset.get("name") or "")
        if name.lower() in ("telearchive.exe", "telearchive"):
            download_url = str(asset.get("browser_download_url") or "") or None
            break

    if not version or not url:
        raise ValueError("Release metadata incomplete")

    return ReleaseInfo(
        version=version,
        tag=tag,
        title=title,
        url=url,
        notes=notes,
        download_url=download_url,
    )


def check_for_update(timeout: float = 8.0) -> UpdateCheckResult:
    current = __version__
    try:
        latest = fetch_latest_release(timeout=timeout)
    except urllib.error.HTTPError as exc:
        return UpdateCheckResult(
            current_version=current,
            latest=None,
            error=f"GitHub API 错误 ({exc.code})",
        )
    except urllib.error.URLError as exc:
        return UpdateCheckResult(
            current_version=current,
            latest=None,
            error=f"网络不可用: {exc.reason}",
        )
    except (TimeoutError, json.JSONDecodeError, ValueError) as exc:
        return UpdateCheckResult(
            current_version=current,
            latest=None,
            error=str(exc),
        )

    if compare_versions(latest.version, current) <= 0:
        return UpdateCheckResult(current_version=current, latest=None)

    return UpdateCheckResult(current_version=current, latest=latest)


def dismiss_update_reminder(version: str) -> None:
    set_dismissed_update_version(version)


def should_notify_update(result: UpdateCheckResult) -> bool:
    return result.has_update and not result.is_dismissed
