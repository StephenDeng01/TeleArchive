from pathlib import Path

from telearchive.settings import (
    get_dismissed_update_version,
    set_dismissed_update_version,
)
from telearchive.updater import (
    UpdateCheckResult,
    compare_versions,
    should_notify_update,
)


def test_compare_versions() -> None:
    assert compare_versions("0.3.0", "0.2.0") > 0
    assert compare_versions("0.2.0", "0.3.0") < 0
    assert compare_versions("v1.0.0", "1.0.0") == 0


def test_dismissed_version_skips_notify(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    set_dismissed_update_version("0.3.0")

    result = UpdateCheckResult(
        current_version="0.2.0",
        latest=_fake_release("0.3.0"),
    )
    assert get_dismissed_update_version() == "0.3.0"
    assert result.has_update
    assert not should_notify_update(result)


def test_should_notify_when_not_dismissed(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    set_dismissed_update_version("0.2.0")

    result = UpdateCheckResult(
        current_version="0.2.0",
        latest=_fake_release("0.3.0"),
    )
    assert should_notify_update(result)


def _fake_release(version: str):
    from telearchive.updater import ReleaseInfo

    return ReleaseInfo(
        version=version,
        tag=f"v{version}",
        title=f"v{version}",
        url="https://example.com/release",
        notes="test",
        download_url=None,
    )
