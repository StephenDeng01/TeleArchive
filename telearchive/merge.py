"""Ingest and merge export files into the database."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from telearchive.db import Database, IngestStats
from telearchive.parser import ParsedChat, iter_export_files, parse_export_file


@dataclass(frozen=True)
class ExportChatSummary:
    source_path: str
    chat_id: int
    chat_name: str
    message_count: int


def inspect_export_chats(paths: list[Path]) -> list[ExportChatSummary]:
    parsed_batches = _parse_exports(paths)
    summaries: list[ExportChatSummary] = []
    for export_file, chats in parsed_batches:
        for chat in chats:
            summaries.append(
                ExportChatSummary(
                    source_path=str(export_file),
                    chat_id=chat.chat_id,
                    chat_name=chat.name,
                    message_count=len(chat.messages),
                )
            )
    return summaries


def ingest_paths(
    db: Database, paths: list[Path], *, allow_mixed_chats: bool = False
) -> list[tuple[str, IngestStats]]:
    """Import all result.json files found under the given paths."""
    parsed_batches = _parse_exports(paths)
    _validate_chat_scope(db, parsed_batches, allow_mixed_chats=allow_mixed_chats)

    results: list[tuple[str, IngestStats]] = []

    for resolved, chats in parsed_batches:
        total = IngestStats()
        for chat in chats:
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


def _validate_chat_scope(
    db: Database,
    parsed_batches: list[tuple[Path, list[ParsedChat]]],
    *,
    allow_mixed_chats: bool,
) -> None:
    if allow_mixed_chats:
        return

    db_chats = db.list_chat_stats()
    db_chat_ids = {chat.chat_id for chat in db_chats}
    incoming_chat_ids = {chat.chat_id for _, chats in parsed_batches for chat in chats}

    if len(db_chat_ids) > 1:
        raise ValueError("数据库中已有多个群聊，请先拆分数据库后再导入。")
    if len(incoming_chat_ids) > 1:
        raise ValueError("本次导入包含多个群聊，请一次仅导入同一个群聊。")
    if db_chat_ids and incoming_chat_ids and db_chat_ids != incoming_chat_ids:
        existing = db_chats[0]
        incoming_chat = next(
            chat for _, chats in parsed_batches for chat in chats if chat.chat_id in incoming_chat_ids
        )
        raise ValueError(
            "检测到导入群聊与数据库现有群聊不一致："
            f"当前库为 {existing.name}({existing.chat_id})，"
            f"本次导入为 {incoming_chat.name}({incoming_chat.chat_id})。"
        )


def _parse_exports(paths: list[Path]) -> list[tuple[Path, list[ParsedChat]]]:
    export_files = _collect_export_files(paths)
    batches: list[tuple[Path, list[ParsedChat]]] = []
    for export_file in export_files:
        resolved = export_file.resolve()
        batches.append((resolved, parse_export_file(resolved)))
    return batches


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
