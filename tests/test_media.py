import json
from pathlib import Path

from telearchive.db import Database
from telearchive.media import extract_media_refs, resolve_attachments
from telearchive.merge import ingest_paths


def test_extract_media_refs() -> None:
    msg = {
        "id": 10,
        "photo": "photos/a.jpg",
        "file": "video_files/v.mp4",
        "media_type": "video_file",
        "thumbnail": "video_files/v_thumb.jpg",
    }
    refs = extract_media_refs(msg)
    kinds = {k for k, _ in refs}
    assert kinds == {"photo", "video_file", "thumbnail"}
    assert ("video_file", "video_files/v.mp4") in refs
    assert ("thumbnail", "photos/a_thumb.jpg") in refs


def test_ingest_indexes_media_on_disk(tmp_path: Path) -> None:
    export_dir = tmp_path / "export"
    photos = export_dir / "photos"
    photos.mkdir(parents=True)
    img = photos / "pic.jpg"
    img.write_bytes(b"fake-image")

    export_data = {
        "name": "测试群",
        "type": "private_supergroup",
        "id": -100999,
        "messages": [
            {
                "id": 1,
                "type": "message",
                "date_unixtime": "1716199200",
                "from": "Alice",
                "from_id": "user1",
                "photo": "photos/pic.jpg",
            }
        ],
    }
    (export_dir / "result.json").write_text(
        json.dumps(export_data), encoding="utf-8"
    )

    db_path = tmp_path / "test.db"
    with Database(db_path) as db:
        ingest_paths(db, [export_dir])
        canonical = db._conn.execute(
            """
            SELECT preferred_relative_path, preferred_absolute_path, location_count
            FROM message_media WHERE message_id = 1
            """
        ).fetchone()
        location = db._conn.execute(
            "SELECT content_hash FROM media_locations WHERE message_id = 1"
        ).fetchone()

    assert canonical["preferred_relative_path"] == "photos/pic.jpg"
    assert Path(canonical["preferred_absolute_path"]) == img.resolve()
    assert canonical["location_count"] == 1
    assert location["content_hash"] is not None

    att = resolve_attachments(export_dir, export_data["messages"][0])[0]
    assert att.exists
    assert att.content_hash == location["content_hash"]


def test_same_media_renamed_across_exports(tmp_path: Path) -> None:
    payload = b"same-binary-content"

    export_a = tmp_path / "export_a"
    (export_a / "photos").mkdir(parents=True)
    (export_a / "photos" / "photo_27@day.jpg").write_bytes(payload)
    export_b = tmp_path / "export_b"
    (export_b / "photos").mkdir(parents=True)
    (export_b / "photos" / "photo_1@day.jpg").write_bytes(payload)

    base = {
        "name": "群",
        "type": "private_supergroup",
        "id": 100,
        "messages": [
            {
                "id": 42,
                "type": "message",
                "date_unixtime": "1716199200",
                "photo": "photos/photo_27@day.jpg",
            }
        ],
    }
    (export_a / "result.json").write_text(json.dumps(base), encoding="utf-8")
    alt = dict(base)
    alt["messages"] = [
        {
            **base["messages"][0],
            "photo": "photos/photo_1@day.jpg",
        }
    ]
    (export_b / "result.json").write_text(json.dumps(alt), encoding="utf-8")

    db_path = tmp_path / "test.db"
    with Database(db_path) as db:
        ingest_paths(db, [export_a, export_b])
        canonical = db._conn.execute(
            "SELECT location_count, content_hash FROM message_media WHERE message_id = 42"
        ).fetchone()
        locations = db._conn.execute(
            "SELECT relative_path FROM media_locations WHERE message_id = 42 ORDER BY id"
        ).fetchall()

    assert canonical["location_count"] == 2
    assert len(locations) == 2
    assert {r["relative_path"] for r in locations} == {
        "photos/photo_27@day.jpg",
        "photos/photo_1@day.jpg",
    }
