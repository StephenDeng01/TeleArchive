from pathlib import Path

from telearchive.media import resolve_attachments


def test_rejects_path_traversal_outside_export_root(tmp_path: Path) -> None:
    export = tmp_path / "export"
    export.mkdir()
    secret = tmp_path / "secret.txt"
    secret.write_text("outside", encoding="utf-8")

    msg = {"id": 1, "photo": "../secret.txt"}
    attachments = resolve_attachments(export, msg)
    assert attachments == []
