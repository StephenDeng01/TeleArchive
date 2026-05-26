import shutil
from pathlib import Path

import pytest

from telearchive.db import Database
from telearchive.merge import ingest_paths
from telearchive.parser import iter_export_files

FIXTURES = Path(__file__).parent / "fixtures"


def _write_export_batch(batch_dir: Path, fixture_name: str) -> None:
    batch_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(FIXTURES / fixture_name, batch_dir / "result.json")


def test_ingest_and_dedupe(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    with Database(db_path) as db:
        ingest_paths(db, [FIXTURES / "single_chat.json"])
        ingest_paths(db, [FIXTURES / "overlap_export.json"])
        stats = db.list_chat_stats()

    assert len(stats) == 1
    assert stats[0].message_count == 3

    with Database(db_path) as db:
        row = db._conn.execute(
            "SELECT text, edited_unixtime FROM messages WHERE message_id = 2"
        ).fetchone()
    assert row["text"] == "第二条（已编辑）"
    assert row["edited_unixtime"] == 1716282000


def test_missing_path(tmp_path: Path) -> None:
    with Database(tmp_path / "t.db") as db:
        with pytest.raises(FileNotFoundError):
            ingest_paths(db, [tmp_path / "nope"])


def test_iter_export_files_from_parent_folder(tmp_path: Path) -> None:
    parent = tmp_path / "exports"
    _write_export_batch(parent / "ChatExport_2026-05-20", "single_chat.json")
    _write_export_batch(parent / "ChatExport_2026-05-26", "overlap_export.json")

    files = list(iter_export_files(parent))
    assert len(files) == 2


def test_merge_batches_under_parent_folder(tmp_path: Path) -> None:
    parent = tmp_path / "exports"
    _write_export_batch(parent / "ChatExport_2026-05-20", "single_chat.json")
    _write_export_batch(parent / "ChatExport_2026-05-26", "overlap_export.json")

    db_path = tmp_path / "test.db"
    with Database(db_path) as db:
        results = ingest_paths(db, [parent])
        stats = db.list_chat_stats()[0]
        import_count = db._conn.execute("SELECT COUNT(*) c FROM imports").fetchone()["c"]

    assert len(results) == 2
    assert stats.message_count == 3
    assert import_count == 2
