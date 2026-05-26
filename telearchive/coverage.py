"""Analyze merged chat archives for gaps and export coverage."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class IdGap:
    chat_id: int
    after_id: int
    before_id: int
    missing_count: int


@dataclass(frozen=True)
class ExportCoverage:
    source_path: str
    imported_at: str
    messages_seen: int
    messages_new: int
    exclusive_count: int


def find_id_gaps(conn: sqlite3.Connection, chat_id: int, *, min_gap: int = 1) -> list[IdGap]:
    """Find discontinuities in Telegram message id sequence."""
    rows = conn.execute(
        """
        SELECT message_id FROM messages
        WHERE chat_id = ? AND msg_type = 'message'
        ORDER BY message_id
        """,
        (chat_id,),
    ).fetchall()
    ids = [int(r[0]) for r in rows]
    gaps: list[IdGap] = []
    for left, right in zip(ids, ids[1:]):
        missing = right - left - 1
        if missing >= min_gap:
            gaps.append(
                IdGap(
                    chat_id=chat_id,
                    after_id=left,
                    before_id=right,
                    missing_count=missing,
                )
            )
    return gaps


def export_coverage(conn: sqlite3.Connection, chat_id: int) -> list[ExportCoverage]:
    """
    For each import batch, count messages first seen in that batch.

    Compare ``exclusive_count`` across batches with ``gaps`` and ingest summary
    to interpret auto-deleted history.
    """
    rows = conn.execute(
        """
        SELECT
            i.source_path,
            i.imported_at,
            i.messages_seen,
            i.messages_new,
            COUNT(m.message_id) AS exclusive_count
        FROM imports i
        LEFT JOIN messages m
            ON m.chat_id = ?
           AND m.first_source_path = i.source_path
        GROUP BY i.id, i.source_path, i.imported_at, i.messages_seen, i.messages_new
        ORDER BY i.id
        """,
        (chat_id,),
    ).fetchall()
    return [
        ExportCoverage(
            source_path=r["source_path"],
            imported_at=r["imported_at"],
            messages_seen=int(r["messages_seen"]),
            messages_new=int(r["messages_new"]),
            exclusive_count=int(r["exclusive_count"] or 0),
        )
        for r in rows
    ]


def count_orphan_preserved(conn: sqlite3.Connection, chat_id: int) -> int:
    """Messages only present in older exports (not re-seen in the latest import)."""
    latest = conn.execute(
        "SELECT source_path FROM imports ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if latest is None:
        return 0
    latest_path = latest["source_path"]
    row = conn.execute(
        """
        SELECT COUNT(*) AS c FROM messages
        WHERE chat_id = ?
          AND first_source_path IS NOT NULL
          AND first_source_path != ?
          AND last_seen_at = first_seen_at
        """,
        (chat_id, latest_path),
    ).fetchone()
    return int(row["c"] or 0)
