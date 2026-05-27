"""Utilities for backing up, rolling back, and splitting TeleArchive databases."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from telearchive.db import Database


def _ts_compact() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def default_backup_dir(db_path: Path) -> Path:
    # Keep backups next to DB for portability (Windows E: drive friendly).
    return db_path.resolve().parent / "telearchive-backups"


def create_db_backup(db_path: Path) -> Path:
    """Create a timestamped copy of db_path and return backup path."""
    src = db_path.resolve()
    if not src.is_file():
        raise FileNotFoundError(f"数据库不存在: {src}")
    bdir = default_backup_dir(src)
    bdir.mkdir(parents=True, exist_ok=True)
    backup = bdir / f"{src.stem}.{_ts_compact()}.bak.db"
    shutil.copy2(src, backup)
    return backup


def rollback_db_from_backup(db_path: Path, backup_path: Path) -> None:
    """Replace db_path with backup_path (after validating)."""
    dst = db_path.resolve()
    src = backup_path.resolve()
    if not src.is_file():
        raise FileNotFoundError(f"备份文件不存在: {src}")
    if src.suffix.lower() != ".db":
        # We only produce *.bak.db but keep it permissive: must end with .db
        raise ValueError(f"备份文件格式不正确（应为 .db）: {src}")
    if not dst.exists():
        # If DB missing, restore is still valid.
        dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


@dataclass(frozen=True)
class SplitResult:
    chat_id: int
    chat_name: str
    output_db: Path
    message_count: int


def split_db_by_chat(db_path: Path, out_dir: Path) -> list[SplitResult]:
    """Split a mixed-chat database into one-db-per-chat."""
    src = db_path.resolve()
    if not src.is_file():
        raise FileNotFoundError(f"数据库不存在: {src}")
    out = out_dir.resolve()
    out.mkdir(parents=True, exist_ok=True)

    results: list[SplitResult] = []
    with Database(src) as db:
        chats = db.list_chat_stats()
        if not chats:
            raise ValueError("数据库中没有聊天记录，无法拆分。")

        for chat in chats:
            target = out / f"{src.stem}.chat_{chat.chat_id}.db"
            if target.exists():
                target.unlink()
            with Database(target) as out_db:
                out_db.init_schema()
                _copy_chat(db, out_db, chat.chat_id)
                # Carry minimal chat meta with updated name/type.
                row = db.get_chat(chat.chat_id)
                if row is not None:
                    from telearchive.parser import ParsedChat  # local import

                    out_db.upsert_chat(
                        ParsedChat(
                            chat_id=int(row["chat_id"]),
                            name=str(row["name"]),
                            chat_type=str(row["chat_type"]) if row["chat_type"] is not None else None,
                            messages=[],
                            export_root=Path("."),
                        )
                    )

                # Count messages
                c = out_db._conn.execute(
                    "SELECT COUNT(*) c FROM messages WHERE chat_id = ?",
                    (chat.chat_id,),
                ).fetchone()["c"]
            results.append(
                SplitResult(
                    chat_id=chat.chat_id,
                    chat_name=chat.name,
                    output_db=target,
                    message_count=int(c),
                )
            )

    return results


def _copy_chat(src_db: Database, dst_db: Database, chat_id: int) -> None:
    # chats row is inserted separately via upsert_chat; still copy raw row too.
    chat_row = src_db._conn.execute(
        "SELECT chat_id, name, chat_type, updated_at FROM chats WHERE chat_id = ?",
        (chat_id,),
    ).fetchone()
    if chat_row is not None:
        dst_db._conn.execute(
            "INSERT OR REPLACE INTO chats(chat_id, name, chat_type, updated_at) VALUES (?, ?, ?, ?)",
            (chat_row["chat_id"], chat_row["name"], chat_row["chat_type"], chat_row["updated_at"]),
        )

    # messages
    msg_rows = src_db._conn.execute(
        "SELECT * FROM messages WHERE chat_id = ?",
        (chat_id,),
    ).fetchall()
    for r in msg_rows:
        dst_db._conn.execute(
            """
            INSERT INTO messages (
                chat_id, message_id, msg_type, date_unixtime, date_iso,
                from_name, from_id, reply_to_id, text, media_type, edited_unixtime,
                raw_json, first_source_path, first_seen_at, last_seen_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                r["chat_id"],
                r["message_id"],
                r["msg_type"],
                r["date_unixtime"],
                r["date_iso"],
                r["from_name"],
                r["from_id"],
                r["reply_to_id"],
                r["text"],
                r["media_type"],
                r["edited_unixtime"],
                r["raw_json"],
                r["first_source_path"],
                r["first_seen_at"],
                r["last_seen_at"],
            ),
        )

    # media_locations
    loc_rows = src_db._conn.execute(
        "SELECT * FROM media_locations WHERE chat_id = ?",
        (chat_id,),
    ).fetchall()
    for r in loc_rows:
        dst_db._conn.execute(
            """
            INSERT INTO media_locations (
                chat_id, message_id, media_kind, export_root, relative_path, absolute_path,
                file_exists, size_bytes, content_hash, first_seen_at, last_seen_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                r["chat_id"],
                r["message_id"],
                r["media_kind"],
                r["export_root"],
                r["relative_path"],
                r["absolute_path"],
                r["file_exists"],
                r["size_bytes"],
                r["content_hash"],
                r["first_seen_at"],
                r["last_seen_at"],
            ),
        )

    # message_media: rebuild from locations in destination for correctness
    dst_db._rebuild_canonical_media()

    # imports: best-effort mapping by first_source_path observed in this chat
    src_paths = {
        str(r["first_source_path"])
        for r in msg_rows
        if r["first_source_path"] is not None
    }
    if src_paths:
        placeholders = ",".join("?" * len(src_paths))
        imp_rows = src_db._conn.execute(
            f"SELECT * FROM imports WHERE source_path IN ({placeholders}) ORDER BY id",
            tuple(src_paths),
        ).fetchall()
        for r in imp_rows:
            dst_db._conn.execute(
                """
                INSERT INTO imports (
                    source_path, imported_at, messages_seen, messages_new, messages_updated,
                    media_refs, media_found, media_missing
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    r["source_path"],
                    r["imported_at"],
                    r["messages_seen"],
                    r["messages_new"],
                    r["messages_updated"],
                    r["media_refs"],
                    r["media_found"],
                    r["media_missing"],
                ),
            )

    dst_db._conn.commit()

