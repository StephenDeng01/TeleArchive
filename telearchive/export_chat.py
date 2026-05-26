"""Export merged messages to Telegram Desktop-compatible JSON folders."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from telearchive.db import Database
from telearchive.export_dates import parse_bound
from telearchive.media import extract_media_refs


@dataclass
class ExportResult:
    output_dir: Path
    chat_id: int
    chat_name: str
    message_count: int
    media_copied: int
    media_missing: int


def export_chat_range(
    db: Database,
    output_dir: Path,
    chat_id: int,
    *,
    from_bound: str,
    to_bound: str,
    include_media: bool = True,
) -> ExportResult:
    """Write ``result.json`` and media subfolders for messages in [from, to]."""
    start_ts = parse_bound(from_bound, end_of_day=False)
    end_ts = parse_bound(to_bound, end_of_day=True)
    if start_ts > end_ts:
        raise ValueError(f"开始时间不能晚于结束时间: {from_bound} > {to_bound}")

    chat = db.get_chat(chat_id)
    if chat is None:
        raise ValueError(f"数据库中不存在群聊 id={chat_id}")

    rows = db.fetch_messages_in_range(chat_id, start_ts, end_ts)
    if not rows:
        raise ValueError("该时间范围内没有消息")

    messages: list[dict[str, Any]] = []
    for row in rows:
        try:
            obj = json.loads(row["raw_json"])
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            messages.append(obj)

    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    media_copied = 0
    media_missing = 0
    if include_media:
        media_copied, media_missing = _copy_media_files(
            db, chat_id, messages, output_dir
        )

    export_doc = {
        "name": chat["name"],
        "type": chat["chat_type"] or "private_supergroup",
        "id": chat_id,
        "messages": messages,
    }
    result_path = output_dir / "result.json"
    result_path.write_text(
        json.dumps(export_doc, ensure_ascii=False, indent=1),
        encoding="utf-8",
    )

    return ExportResult(
        output_dir=output_dir,
        chat_id=chat_id,
        chat_name=str(chat["name"]),
        message_count=len(messages),
        media_copied=media_copied,
        media_missing=media_missing,
    )


def _copy_media_files(
    db: Database,
    chat_id: int,
    messages: list[dict[str, Any]],
    output_dir: Path,
) -> tuple[int, int]:
    message_ids = [int(m["id"]) for m in messages if m.get("id") is not None]
    source_map = db.fetch_media_sources(chat_id, message_ids)

    copied = 0
    missing = 0
    seen_dest: set[str] = set()

    for msg in messages:
        mid = msg.get("id")
        if mid is None:
            continue
        for _kind, rel in extract_media_refs(msg):
            if rel in seen_dest:
                continue
            seen_dest.add(rel)

            src = source_map.get((int(mid), rel))
            if src is None:
                missing += 1
                continue

            src_path = Path(src)
            if not src_path.is_file():
                missing += 1
                continue

            dest = output_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            if not dest.exists() or dest.stat().st_size != src_path.stat().st_size:
                shutil.copy2(src_path, dest)
            copied += 1

    return copied, missing
