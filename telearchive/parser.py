"""Parse Telegram Desktop JSON export files."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator


@dataclass(frozen=True)
class ParsedChat:
    chat_id: int
    name: str
    chat_type: str | None
    messages: list[dict[str, Any]]
    export_root: Path


def extract_text(raw: Any) -> str | None:
    """Normalize message text from string or entity array."""
    if raw is None:
        return None
    if isinstance(raw, str):
        return raw
    if isinstance(raw, list):
        parts: list[str] = []
        for item in raw:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and "text" in item:
                parts.append(str(item["text"]))
        return "".join(parts) if parts else None
    return str(raw)


def iter_export_files(path: Path) -> Iterator[Path]:
    """Yield result.json files from a file or directory tree."""
    if path.is_file():
        if path.name == "result.json" or path.suffix.lower() == ".json":
            yield path
        return
    if path.is_dir():
        direct = path / "result.json"
        if direct.is_file():
            yield direct
            return
        child_exports = sorted(
            child / "result.json"
            for child in path.iterdir()
            if child.is_dir() and (child / "result.json").is_file()
        )
        if child_exports:
            for export_file in child_exports:
                yield export_file
            return
        for found in sorted(path.rglob("result.json")):
            yield found


def load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def parse_export_file(path: Path) -> list[ParsedChat]:
    """Parse one export JSON into one or more chats."""
    data = load_json(path)
    export_root = path.resolve().parent
    return list(parse_export_data(data, source_path=str(path), export_root=export_root))


def parse_export_data(
    data: Any,
    *,
    source_path: str = "",
    export_root: Path | None = None,
) -> Iterator[ParsedChat]:
    """Parse export root object (full export, chats wrapper, or single chat)."""
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object in export, got {type(data).__name__}")

    root = export_root or Path(source_path).parent

    if "messages" in data:
        yield _chat_from_object(data, source_path=source_path, export_root=root)
        return

    chats_block = data.get("chats")
    if isinstance(chats_block, dict) and isinstance(chats_block.get("list"), list):
        for chat in chats_block["list"]:
            if isinstance(chat, dict) and "messages" in chat:
                yield _chat_from_object(chat, source_path=source_path, export_root=root)
        return

    left = data.get("left_chats")
    if isinstance(left, dict) and isinstance(left.get("list"), list):
        for chat in left["list"]:
            if isinstance(chat, dict) and "messages" in chat:
                yield _chat_from_object(chat, source_path=source_path, export_root=root)

    raise ValueError(
        "Unrecognized export format: expected single-chat object or chats.list"
    )


def _chat_from_object(
    chat: dict[str, Any],
    *,
    source_path: str,
    export_root: Path,
) -> ParsedChat:
    raw_id = chat.get("id")
    if raw_id is None:
        raise ValueError(f"Chat missing id in {source_path or 'export'}")
    messages = chat.get("messages")
    if not isinstance(messages, list):
        messages = []
    return ParsedChat(
        chat_id=int(raw_id),
        name=str(chat.get("name") or f"chat_{raw_id}"),
        chat_type=chat.get("type"),
        messages=[m for m in messages if isinstance(m, dict)],
        export_root=export_root,
    )
