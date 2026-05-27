import json
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


def _write_chat_export(path: Path, *, chat_id: int, name: str, msg_id: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "id": chat_id,
        "name": name,
        "type": "supergroup",
        "messages": [
            {
                "id": msg_id,
                "type": "message",
                "date": "2026-05-28T00:00:00",
                "date_unixtime": "1748390400",
                "from": "tester",
                "from_id": "user1",
                "text": f"hello-{msg_id}",
            }
        ],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


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


def test_block_mixed_chat_ingest_by_default(tmp_path: Path) -> None:
    export_a = tmp_path / "a" / "result.json"
    export_b = tmp_path / "b" / "result.json"
    _write_chat_export(export_a, chat_id=1001, name="群A", msg_id=1)
    _write_chat_export(export_b, chat_id=2002, name="群B", msg_id=1)

    with Database(tmp_path / "mixed.db") as db:
        with pytest.raises(ValueError):
            ingest_paths(db, [export_a.parent, export_b.parent])


def test_allow_mixed_chat_ingest_when_opt_in(tmp_path: Path) -> None:
    export_a = tmp_path / "a" / "result.json"
    export_b = tmp_path / "b" / "result.json"
    _write_chat_export(export_a, chat_id=1001, name="群A", msg_id=1)
    _write_chat_export(export_b, chat_id=2002, name="群B", msg_id=1)

    with Database(tmp_path / "mixed-ok.db") as db:
        ingest_paths(db, [export_a.parent, export_b.parent], allow_mixed_chats=True)
        chats = db.list_chat_stats()

    assert {chat.chat_id for chat in chats} == {1001, 2002}
