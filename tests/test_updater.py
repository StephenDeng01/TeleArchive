from pathlib import Path

from telearchive.settings import (
    get_dismissed_update_version,
    set_dismissed_update_version,
)
from telearchive.updater import (
    ReleaseInfo,
    UpdateCheckResult,
    compare_versions,
    fetch_latest_release,
    pick_newer_release,
    should_notify_update,
)


def test_pick_newer_release() -> None:
    old = _fake_release("0.6.7")
    new = _fake_release("0.6.8")
    assert pick_newer_release(old, new) == new
    assert pick_newer_release(new, old) == new
    assert pick_newer_release(None, new) == new


def test_fetch_latest_release_uses_newer_api(monkeypatch) -> None:
    manifest = _fake_release("0.6.7")
    api = _fake_release("0.6.8")
    api = ReleaseInfo(
        version=api.version,
        tag=api.tag,
        title=api.title,
        url=api.url,
        notes=api.notes,
        download_url="https://example.com/TeleArchive.exe",
        sha256=None,
    )

    monkeypatch.setattr(
        "telearchive.updater.fetch_latest_from_manifest",
        lambda **_: manifest,
    )
    monkeypatch.setattr(
        "telearchive.updater.fetch_latest_from_api",
        lambda **_: api,
    )
    latest = fetch_latest_release()
    assert latest.version == "0.6.8"


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


def test_resolve_prefers_sidecar_over_manifest(monkeypatch) -> None:
    from telearchive.updater import ReleaseInfo, resolve_release_sha256

    release = ReleaseInfo(
        version="0.6.5",
        tag="v0.6.5",
        title="v0.6.5",
        url="https://example.com",
        notes="",
        download_url="https://example.com/TeleArchive.exe",
        sha256="6e604498aabd6f63ebe8295777daf7c06f9e652820b4c65ebc7555378133d6d9",
    )

    def fake_sidecar(url: str, *, timeout: float) -> str | None:
        return "c12a8c36f77111351bf3897955133ec10cf01b09db6be21053c3589e3f3e7800"

    monkeypatch.setattr("telearchive.updater._try_fetch_sha256_sidecar", fake_sidecar)
    resolved = resolve_release_sha256(release)
    assert resolved.sha256 == "c12a8c36f77111351bf3897955133ec10cf01b09db6be21053c3589e3f3e7800"


def test_should_notify_when_not_dismissed(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    set_dismissed_update_version("0.2.0")

    result = UpdateCheckResult(
        current_version="0.2.0",
        latest=_fake_release("0.3.0"),
    )
    assert should_notify_update(result)


def test_updater_script_waits_for_pid_and_cleans_pyi(tmp_path: Path) -> None:
    from telearchive.updater import _build_windows_updater_script

    script = _build_windows_updater_script(
        current_exe=tmp_path / "TeleArchive.exe",
        new_exe=tmp_path / "TeleArchive-0.8.8.exe",
        parent_pid=4242,
    )
    assert "$ParentPid = 4242" in script
    assert "Wait-Process -Id $ParentPid" in script
    assert "Clear-PyiExtracts" in script
    assert "TeleArchive\\_pyi" in script


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
