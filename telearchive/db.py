"""SQLite persistence for merged Telegram messages."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from telearchive.media import MediaAttachment, resolve_attachments
from telearchive.parser import ParsedChat, extract_text


SCHEMA = """
CREATE TABLE IF NOT EXISTS chats (
    chat_id     INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    chat_type   TEXT,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS imports (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    source_path     TEXT NOT NULL,
    imported_at     TEXT NOT NULL,
    messages_seen   INTEGER NOT NULL DEFAULT 0,
    messages_new    INTEGER NOT NULL DEFAULT 0,
    messages_updated INTEGER NOT NULL DEFAULT 0,
    media_refs      INTEGER NOT NULL DEFAULT 0,
    media_found     INTEGER NOT NULL DEFAULT 0,
    media_missing   INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS messages (
    chat_id         INTEGER NOT NULL,
    message_id      INTEGER NOT NULL,
    msg_type        TEXT NOT NULL,
    date_unixtime   INTEGER NOT NULL,
    date_iso        TEXT,
    from_name       TEXT,
    from_id         TEXT,
    reply_to_id     INTEGER,
    text            TEXT,
    media_type      TEXT,
    edited_unixtime INTEGER,
    raw_json        TEXT NOT NULL,
    first_source_path TEXT,
    first_seen_at   TEXT NOT NULL,
    last_seen_at    TEXT NOT NULL,
    PRIMARY KEY (chat_id, message_id),
    FOREIGN KEY (chat_id) REFERENCES chats(chat_id)
);

CREATE TABLE IF NOT EXISTS message_media (
    chat_id         INTEGER NOT NULL,
    message_id      INTEGER NOT NULL,
    media_kind      TEXT NOT NULL,
    content_hash    TEXT,
    size_bytes      INTEGER,
    preferred_absolute_path TEXT,
    preferred_export_root   TEXT,
    preferred_relative_path TEXT,
    location_count  INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (chat_id, message_id, media_kind),
    FOREIGN KEY (chat_id, message_id) REFERENCES messages(chat_id, message_id)
);

CREATE TABLE IF NOT EXISTS media_locations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id         INTEGER NOT NULL,
    message_id      INTEGER NOT NULL,
    media_kind      TEXT NOT NULL,
    export_root     TEXT NOT NULL,
    relative_path   TEXT NOT NULL,
    absolute_path   TEXT NOT NULL,
    file_exists     INTEGER NOT NULL DEFAULT 0,
    size_bytes      INTEGER,
    content_hash    TEXT,
    first_seen_at   TEXT NOT NULL,
    last_seen_at    TEXT NOT NULL,
    UNIQUE(chat_id, message_id, media_kind, export_root, relative_path),
    FOREIGN KEY (chat_id, message_id) REFERENCES messages(chat_id, message_id)
);

CREATE INDEX IF NOT EXISTS idx_messages_chat_time
    ON messages (chat_id, date_unixtime, message_id);

CREATE INDEX IF NOT EXISTS idx_media_locations_chat
    ON media_locations (chat_id, message_id, media_kind);
"""


@dataclass
class IngestStats:
    messages_seen: int = 0
    messages_new: int = 0
    messages_updated: int = 0
    media_refs: int = 0
    media_found: int = 0
    media_missing: int = 0


@dataclass
class ChatStats:
    chat_id: int
    name: str
    message_count: int
    earliest: int | None
    latest: int | None


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self.init_schema()

    def close(self) -> None:
        self._conn.commit()
        self._conn.close()

    def __enter__(self) -> Database:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def init_schema(self) -> None:
        self._conn.executescript(SCHEMA)
        self._migrate_schema()
        self._conn.commit()

    def _migrate_schema(self) -> None:
        """Upgrade databases created by earlier TeleArchive versions."""
        msg_cols = {
            row[1] for row in self._conn.execute("PRAGMA table_info(messages)").fetchall()
        }
        if "media_type" not in msg_cols:
            self._conn.execute("ALTER TABLE messages ADD COLUMN media_type TEXT")
        if "first_source_path" not in msg_cols:
            self._conn.execute("ALTER TABLE messages ADD COLUMN first_source_path TEXT")

        import_cols = {
            row[1] for row in self._conn.execute("PRAGMA table_info(imports)").fetchall()
        }
        for col, ddl in (
            ("media_refs", "ALTER TABLE imports ADD COLUMN media_refs INTEGER NOT NULL DEFAULT 0"),
            ("media_found", "ALTER TABLE imports ADD COLUMN media_found INTEGER NOT NULL DEFAULT 0"),
            ("media_missing", "ALTER TABLE imports ADD COLUMN media_missing INTEGER NOT NULL DEFAULT 0"),
        ):
            if col not in import_cols:
                self._conn.execute(ddl)

        media_tables = {
            row[0]
            for row in self._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        if "media_locations" in media_tables:
            return

        old_cols = {
            row[1]
            for row in self._conn.execute("PRAGMA table_info(message_media)").fetchall()
        }
        if "relative_path" not in old_cols:
            return

        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS message_media_new (
                chat_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                media_kind TEXT NOT NULL,
                content_hash TEXT,
                size_bytes INTEGER,
                preferred_absolute_path TEXT,
                preferred_export_root TEXT,
                preferred_relative_path TEXT,
                location_count INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (chat_id, message_id, media_kind)
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS media_locations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                media_kind TEXT NOT NULL,
                export_root TEXT NOT NULL,
                relative_path TEXT NOT NULL,
                absolute_path TEXT NOT NULL,
                file_exists INTEGER NOT NULL DEFAULT 0,
                size_bytes INTEGER,
                content_hash TEXT,
                first_seen_at TEXT NOT NULL,
                last_seen_at TEXT NOT NULL,
                UNIQUE(chat_id, message_id, media_kind, export_root, relative_path)
            )
            """
        )
        self._conn.execute(
            """
            INSERT INTO media_locations (
                chat_id, message_id, media_kind, export_root, relative_path,
                absolute_path, file_exists, size_bytes, content_hash,
                first_seen_at, last_seen_at
            )
            SELECT
                chat_id, message_id, media_kind, export_root, relative_path,
                absolute_path, file_exists, size_bytes, NULL,
                first_seen_at, last_seen_at
            FROM message_media
            """
        )
        self._conn.execute("DROP TABLE message_media")
        self._conn.execute("ALTER TABLE message_media_new RENAME TO message_media")
        self._rebuild_canonical_media()

    def _rebuild_canonical_media(self) -> None:
        rows = self._conn.execute(
            """
            SELECT chat_id, message_id, media_kind FROM media_locations
            GROUP BY chat_id, message_id, media_kind
            """
        ).fetchall()
        for row in rows:
            self._refresh_canonical_media(
                int(row["chat_id"]),
                int(row["message_id"]),
                str(row["media_kind"]),
            )

    def upsert_chat(self, chat: ParsedChat) -> None:
        now = utc_now_iso()
        self._conn.execute(
            """
            INSERT INTO chats (chat_id, name, chat_type, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET
                name = excluded.name,
                chat_type = COALESCE(excluded.chat_type, chats.chat_type),
                updated_at = excluded.updated_at
            """,
            (chat.chat_id, chat.name, chat.chat_type, now),
        )

    def record_import(
        self,
        source_path: str,
        stats: IngestStats,
    ) -> int:
        cur = self._conn.execute(
            """
            INSERT INTO imports (
                source_path, imported_at,
                messages_seen, messages_new, messages_updated,
                media_refs, media_found, media_missing
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                source_path,
                utc_now_iso(),
                stats.messages_seen,
                stats.messages_new,
                stats.messages_updated,
                stats.media_refs,
                stats.media_found,
                stats.media_missing,
            ),
        )
        self._conn.commit()
        return int(cur.lastrowid)

    def upsert_messages(
        self,
        chat_id: int,
        messages: list[dict[str, Any]],
        *,
        export_root: Path,
        source_path: str,
    ) -> IngestStats:
        stats = IngestStats()
        now = utc_now_iso()
        root = export_root.resolve()

        for msg in messages:
            msg_id = msg.get("id")
            if msg_id is None:
                continue
            stats.messages_seen += 1
            mid = int(msg_id)

            row = _message_row(chat_id, msg, now, source_path)
            existing = self._conn.execute(
                """
                SELECT edited_unixtime, raw_json, first_source_path
                FROM messages WHERE chat_id = ? AND message_id = ?
                """,
                (chat_id, mid),
            ).fetchone()

            if existing is None:
                self._insert_message(row)
                stats.messages_new += 1
            elif _should_update(existing, row):
                row["first_source_path"] = existing["first_source_path"]
                self._update_message(row)
                stats.messages_updated += 1
            else:
                self._conn.execute(
                    "UPDATE messages SET last_seen_at = ? WHERE chat_id = ? AND message_id = ?",
                    (now, chat_id, mid),
                )

            media_stats = self._upsert_message_media(chat_id, mid, msg, root, now)
            stats.media_refs += media_stats.media_refs
            stats.media_found += media_stats.media_found
            stats.media_missing += media_stats.media_missing

        self._conn.commit()
        return stats

    def _upsert_message_media(
        self,
        chat_id: int,
        message_id: int,
        msg: dict[str, Any],
        export_root: Path,
        now: str,
    ) -> IngestStats:
        stats = IngestStats()
        for att in resolve_attachments(export_root, msg):
            stats.media_refs += 1
            if att.exists:
                stats.media_found += 1
            else:
                stats.media_missing += 1
            self._upsert_media_location(chat_id, message_id, att, str(export_root), now)
        return stats

    def _upsert_media_location(
        self,
        chat_id: int,
        message_id: int,
        att: MediaAttachment,
        export_root: str,
        now: str,
    ) -> None:
        exists_int = 1 if att.exists else 0
        existing = self._conn.execute(
            """
            SELECT id, file_exists, content_hash FROM media_locations
            WHERE chat_id = ? AND message_id = ? AND media_kind = ?
              AND export_root = ? AND relative_path = ?
            """,
            (chat_id, message_id, att.kind, export_root, att.relative_path),
        ).fetchone()

        if existing is None:
            self._conn.execute(
                """
                INSERT INTO media_locations (
                    chat_id, message_id, media_kind, export_root, relative_path,
                    absolute_path, file_exists, size_bytes, content_hash,
                    first_seen_at, last_seen_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    chat_id,
                    message_id,
                    att.kind,
                    export_root,
                    att.relative_path,
                    str(att.absolute_path),
                    exists_int,
                    att.size_bytes,
                    att.content_hash,
                    now,
                    now,
                ),
            )
        else:
            keep_old = existing["file_exists"] and not att.exists
            if keep_old:
                self._conn.execute(
                    """
                    UPDATE media_locations SET last_seen_at = ? WHERE id = ?
                    """,
                    (now, existing["id"]),
                )
            else:
                self._conn.execute(
                    """
                    UPDATE media_locations SET
                        absolute_path = ?,
                        file_exists = ?,
                        size_bytes = ?,
                        content_hash = COALESCE(?, content_hash),
                        last_seen_at = ?
                    WHERE id = ?
                    """,
                    (
                        str(att.absolute_path),
                        exists_int,
                        att.size_bytes,
                        att.content_hash,
                        now,
                        existing["id"],
                    ),
                )

        self._refresh_canonical_media(chat_id, message_id, att.kind)

    def _refresh_canonical_media(
        self,
        chat_id: int,
        message_id: int,
        media_kind: str,
    ) -> None:
        rows = self._conn.execute(
            """
            SELECT * FROM media_locations
            WHERE chat_id = ? AND message_id = ? AND media_kind = ?
            ORDER BY file_exists DESC, last_seen_at DESC, id DESC
            """,
            (chat_id, message_id, media_kind),
        ).fetchall()
        if not rows:
            self._conn.execute(
                """
                DELETE FROM message_media
                WHERE chat_id = ? AND message_id = ? AND media_kind = ?
                """,
                (chat_id, message_id, media_kind),
            )
            return

        preferred = rows[0]
        content_hash = next((r["content_hash"] for r in rows if r["content_hash"]), None)
        self._conn.execute(
            """
            INSERT INTO message_media (
                chat_id, message_id, media_kind, content_hash, size_bytes,
                preferred_absolute_path, preferred_export_root, preferred_relative_path,
                location_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(chat_id, message_id, media_kind) DO UPDATE SET
                content_hash = excluded.content_hash,
                size_bytes = excluded.size_bytes,
                preferred_absolute_path = excluded.preferred_absolute_path,
                preferred_export_root = excluded.preferred_export_root,
                preferred_relative_path = excluded.preferred_relative_path,
                location_count = excluded.location_count
            """,
            (
                chat_id,
                message_id,
                media_kind,
                content_hash,
                preferred["size_bytes"],
                preferred["absolute_path"],
                preferred["export_root"],
                preferred["relative_path"],
                len(rows),
            ),
        )

    def _insert_message(self, row: dict[str, Any]) -> None:
        self._conn.execute(
            """
            INSERT INTO messages (
                chat_id, message_id, msg_type, date_unixtime, date_iso,
                from_name, from_id, reply_to_id, text, media_type, edited_unixtime,
                raw_json, first_source_path, first_seen_at, last_seen_at
            ) VALUES (
                :chat_id, :message_id, :msg_type, :date_unixtime, :date_iso,
                :from_name, :from_id, :reply_to_id, :text, :media_type, :edited_unixtime,
                :raw_json, :first_source_path, :first_seen_at, :last_seen_at
            )
            """,
            row,
        )

    def _update_message(self, row: dict[str, Any]) -> None:
        self._conn.execute(
            """
            UPDATE messages SET
                msg_type = :msg_type,
                date_unixtime = :date_unixtime,
                date_iso = :date_iso,
                from_name = :from_name,
                from_id = :from_id,
                reply_to_id = :reply_to_id,
                text = :text,
                media_type = :media_type,
                edited_unixtime = :edited_unixtime,
                raw_json = :raw_json,
                last_seen_at = :last_seen_at
            WHERE chat_id = :chat_id AND message_id = :message_id
            """,
            row,
        )

    def list_chat_stats(self) -> list[ChatStats]:
        rows = self._conn.execute(
            """
            SELECT
                c.chat_id,
                c.name,
                COUNT(m.message_id) AS message_count,
                MIN(m.date_unixtime) AS earliest,
                MAX(m.date_unixtime) AS latest
            FROM chats c
            LEFT JOIN messages m ON m.chat_id = c.chat_id
            GROUP BY c.chat_id, c.name
            ORDER BY c.name
            """
        ).fetchall()
        return [
            ChatStats(
                chat_id=r["chat_id"],
                name=r["name"],
                message_count=r["message_count"],
                earliest=r["earliest"],
                latest=r["latest"],
            )
            for r in rows
        ]

    def media_stats(self) -> tuple[int, int, int, int]:
        """Return (logical_media, locations, found, missing)."""
        row = self._conn.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM message_media) AS logical,
                COUNT(*) AS locations,
                COALESCE(SUM(CASE WHEN file_exists = 1 THEN 1 ELSE 0 END), 0) AS found,
                COALESCE(SUM(CASE WHEN file_exists = 0 THEN 1 ELSE 0 END), 0) AS missing
            FROM media_locations
            """
        ).fetchone()
        return (
            int(row["logical"]),
            int(row["locations"]),
            int(row["found"]),
            int(row["missing"]),
        )

    def import_history(self, limit: int = 20) -> list[sqlite3.Row]:
        return self._conn.execute(
            """
            SELECT * FROM imports
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()


def _message_row(
    chat_id: int,
    msg: dict[str, Any],
    now: str,
    source_path: str,
) -> dict[str, Any]:
    date_unix = msg.get("date_unixtime")
    try:
        date_unix_int = int(date_unix) if date_unix is not None else 0
    except (TypeError, ValueError):
        date_unix_int = 0

    edited = msg.get("edited_unixtime")
    try:
        edited_int = int(edited) if edited is not None else None
    except (TypeError, ValueError):
        edited_int = None

    reply = msg.get("reply_to_message_id")
    try:
        reply_int = int(reply) if reply is not None else None
    except (TypeError, ValueError):
        reply_int = None

    return {
        "chat_id": chat_id,
        "message_id": int(msg["id"]),
        "msg_type": str(msg.get("type") or "message"),
        "date_unixtime": date_unix_int,
        "date_iso": msg.get("date"),
        "from_name": msg.get("from"),
        "from_id": msg.get("from_id"),
        "reply_to_id": reply_int,
        "text": extract_text(msg.get("text")),
        "media_type": msg.get("media_type"),
        "edited_unixtime": edited_int,
        "raw_json": json.dumps(msg, ensure_ascii=False),
        "first_source_path": source_path,
        "first_seen_at": now,
        "last_seen_at": now,
    }


def _should_update(existing: sqlite3.Row, new_row: dict[str, Any]) -> bool:
    old_edited = existing["edited_unixtime"]
    new_edited = new_row["edited_unixtime"]
    if new_edited is not None and (old_edited is None or new_edited > old_edited):
        return True
    if new_row["raw_json"] != existing["raw_json"]:
        return True
    return False
