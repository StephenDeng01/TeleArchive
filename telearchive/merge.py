"""Ingest and merge export files into the database."""

from __future__ import annotations

import json
from pathlib import Path

from telearchive.db import Database, IngestStats
from telearchive.parser import iter_export_files, parse_export_file


def ingest_paths(db: Database, paths: list[Path]) -> list[tuple[str, IngestStats]]:
    """Import all result.json files found under the given paths."""
    export_files = _collect_export_files(paths)
    results: list[tuple[str, IngestStats]] = []

    for export_file in export_files:
        resolved = export_file.resolve()
        total = IngestStats()
        for chat in parse_export_file(resolved):
            db.upsert_chat(chat)
            part = db.upsert_messages(
                chat.chat_id,
                chat.messages,
                export_root=chat.export_root,
                source_path=str(resolved),
            )
            total.messages_seen += part.messages_seen
            total.messages_new += part.messages_new
            total.messages_updated += part.messages_updated
            total.media_refs += part.media_refs
            total.media_found += part.media_found
            total.media_missing += part.media_missing

        db.record_import(str(resolved), total)
        results.append((str(resolved), total))

    return results


def _collect_export_files(paths: list[Path]) -> list[Path]:
    seen: set[Path] = set()
    found: list[Path] = []
    for base in paths:
        base = base.resolve()
        if not base.exists():
            raise FileNotFoundError(f"Path not found: {base}")
        for export_file in iter_export_files(base):
            resolved = export_file.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            found.append(resolved)
    return sorted(found, key=_export_sort_key)


def _export_sort_key(path: Path) -> tuple[str, int, str]:
    """
    Ingest older exports first so auto-deleted messages from earlier batches
    are preserved when a newer, shorter export is merged later.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        messages = data.get("messages") or []
        times: list[int] = []
        for msg in messages:
            if isinstance(msg, dict) and msg.get("date_unixtime") is not None:
                try:
                    times.append(int(msg["date_unixtime"]))
                except (TypeError, ValueError):
                    pass
        if times:
            return ("", min(times), path.name)
    except (OSError, json.JSONDecodeError):
        pass
    return ("", int(path.stat().st_mtime), path.name)
