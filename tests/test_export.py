import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from telearchive.db import Database
from telearchive.export_chat import export_chat_range
from telearchive.export_dates import parse_bound, set_shortcut_range
from telearchive.merge import ingest_paths

FIXTURES = Path(__file__).parent / "fixtures"
UTC8 = timezone(timedelta(hours=8))


def test_parse_bound() -> None:
    assert parse_bound("2026-05-20") == parse_bound("2026-05-20T00:00:00")
    start = parse_bound("2026-05-20")
    end = parse_bound("2026-05-20", end_of_day=True)
    assert start == int(datetime(2026, 5, 20, 0, 0, 0, tzinfo=UTC8).timestamp())
    assert end == int(datetime(2026, 5, 20, 23, 59, 59, tzinfo=UTC8).timestamp())
    assert end > start
    assert parse_bound("2026-05-20T15:30:00") == int(
        datetime(2026, 5, 20, 15, 30, 0, tzinfo=UTC8).timestamp()
    )


def test_set_shortcut_range_includes_time() -> None:
    ref = datetime(2026, 5, 27, 14, 0, 0, tzinfo=UTC8)
    start, end = set_shortcut_range("today", now=ref)
    assert start == "2026-05-27T00:00:00"
    assert end == "2026-05-27T23:59:59"


def test_export_json_structure(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    out_dir = tmp_path / "export_out"

    with Database(db_path) as db:
        ingest_paths(db, [FIXTURES / "single_chat.json", FIXTURES / "overlap_export.json"])
        chat_id = db.list_chat_stats()[0].chat_id
        result = export_chat_range(
            db,
            out_dir,
            chat_id,
            from_bound="2024-05-20",
            to_bound="2024-05-20",
            include_media=False,
        )

    assert result.message_count == 2
    data = json.loads((out_dir / "result.json").read_text(encoding="utf-8"))
    assert data["name"] == "测试群"
    assert data["id"] == chat_id
    assert "messages" in data
    assert len(data["messages"]) == 2
    assert (out_dir / "result.json").is_file()


def test_export_with_media_copy(tmp_path: Path) -> None:
    export_dir = tmp_path / "batch"
    photos = export_dir / "photos"
    photos.mkdir(parents=True)
    img = photos / "pic@20-05-2026_10-00-00.jpg"
    img.write_bytes(b"img-bytes")

    chat_doc = {
        "name": "媒体群",
        "type": "private_supergroup",
        "id": 999,
        "messages": [
            {
                "id": 10,
                "type": "message",
                "date": "2026-05-20T10:00:00",
                "date_unixtime": "1716199200",
                "from": "A",
                "from_id": "user1",
                "photo": "photos/pic@20-05-2026_10-00-00.jpg",
            }
        ],
    }
    (export_dir / "result.json").write_text(json.dumps(chat_doc), encoding="utf-8")

    db_path = tmp_path / "test.db"
    out_dir = tmp_path / "slice"

    with Database(db_path) as db:
        ingest_paths(db, [export_dir])
        result = export_chat_range(
            db,
            out_dir,
            999,
            from_bound="2024-05-20",
            to_bound="2024-05-20",
            include_media=True,
        )

    assert result.media_copied == 1
    assert (out_dir / "photos" / "pic@20-05-2026_10-00-00.jpg").read_bytes() == b"img-bytes"


def test_export_empty_range_raises(tmp_path: Path) -> None:
    db_path = tmp_path / "test.db"
    with Database(db_path) as db:
        ingest_paths(db, [FIXTURES / "single_chat.json"])
        chat_id = db.list_chat_stats()[0].chat_id
        with pytest.raises(ValueError, match="没有消息"):
            export_chat_range(
                db,
                tmp_path / "out",
                chat_id,
                from_bound="2030-01-01",
                to_bound="2030-01-02",
            )
