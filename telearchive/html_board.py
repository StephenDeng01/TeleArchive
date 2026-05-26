"""Build Telegram-like HTML previews for GUI board from merged DB messages."""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from telearchive.db import Database
from telearchive.media import extract_media_refs
from telearchive.parser import extract_text

UTC8 = timezone(timedelta(hours=8))
ALL_FROM = "1970-01-01"
ALL_TO = "2099-12-31"


@dataclass
class BoardRenderResult:
    chat_id: int
    chat_name: str
    from_ts: int
    to_ts: int
    message_count: int
    html_path: Path
    json_path: Path
    cached: bool


def parse_local_bound(value: str, *, end_of_day: bool = False) -> int:
    text = value.strip()
    if re.fullmatch(r"\d{9,12}", text):
        return int(text)

    normalized = text.replace(" ", "T")
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(normalized, fmt)
            if fmt == "%Y-%m-%d" and end_of_day:
                dt = dt.replace(hour=23, minute=59, second=59)
            return int(dt.replace(tzinfo=UTC8).timestamp())
        except ValueError:
            continue
    raise ValueError(
        f"无法解析时间: {value!r}，请使用 YYYY-MM-DD 或 YYYY-MM-DDTHH:MM:SS 或 Unix 时间戳"
    )


def set_shortcut_range(name: str, now: datetime | None = None) -> tuple[str, str]:
    ref = now.astimezone(UTC8) if now else datetime.now(UTC8)
    today = ref.date()
    if name == "today":
        start = today
    elif name == "3d":
        start = today - timedelta(days=2)
    elif name == "7d":
        start = today - timedelta(days=6)
    elif name == "30d":
        start = today - timedelta(days=29)
    elif name == "all":
        return (ALL_FROM, ALL_TO)
    else:
        raise ValueError(f"未知快捷范围: {name}")
    return (start.isoformat(), today.isoformat())


def render_range_to_cache(
    db: Database,
    cache_dir: Path,
    chat_id: int,
    from_text: str,
    to_text: str,
) -> BoardRenderResult:
    from_ts = parse_local_bound(from_text, end_of_day=False)
    to_ts = parse_local_bound(to_text, end_of_day=True)
    if from_ts > to_ts:
        raise ValueError(f"开始时间不能晚于结束时间: {from_text} > {to_text}")

    chat = db.get_chat(chat_id)
    if chat is None:
        raise ValueError(f"数据库中不存在群聊 id={chat_id}")
    chat_name = str(chat["name"])

    key = f"chat_{chat_id}_{from_ts}_{to_ts}"
    chat_dir = (cache_dir / f"chat_{chat_id}").resolve()
    chat_dir.mkdir(parents=True, exist_ok=True)
    json_path = chat_dir / f"{key}.json"
    html_path = chat_dir / f"{key}.html"
    if html_path.is_file() and json_path.is_file():
        count = _load_count(json_path)
        return BoardRenderResult(
            chat_id=chat_id,
            chat_name=chat_name,
            from_ts=from_ts,
            to_ts=to_ts,
            message_count=count,
            html_path=html_path,
            json_path=json_path,
            cached=True,
        )

    rows = db.fetch_messages_in_range(chat_id, from_ts, to_ts)
    if not rows:
        raise ValueError("该时间范围内没有消息")
    messages: list[dict[str, Any]] = []
    for row in rows:
        try:
            msg = json.loads(row["raw_json"])
        except json.JSONDecodeError:
            continue
        if isinstance(msg, dict):
            messages.append(msg)
    if not messages:
        raise ValueError("该时间范围内没有可渲染消息")

    message_ids = [int(m["id"]) for m in messages if m.get("id") is not None]
    media_map = db.fetch_media_sources(chat_id, message_ids)
    html_text = _render_html(chat_name, messages, media_map)
    html_path.write_text(html_text, encoding="utf-8")
    json_path.write_text(
        json.dumps(
            {
                "chat_id": chat_id,
                "chat_name": chat_name,
                "from_ts": from_ts,
                "to_ts": to_ts,
                "message_count": len(messages),
                "messages": messages,
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    return BoardRenderResult(
        chat_id=chat_id,
        chat_name=chat_name,
        from_ts=from_ts,
        to_ts=to_ts,
        message_count=len(messages),
        html_path=html_path,
        json_path=json_path,
        cached=False,
    )


def warmup_all_messages_cache(db_path: Path, cache_dir: Path, chat_id: int) -> None:
    with Database(db_path) as db:
        render_range_to_cache(db, cache_dir, chat_id, ALL_FROM, ALL_TO)


def _load_count(path: Path) -> int:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0
    if isinstance(payload, dict):
        try:
            return int(payload.get("message_count") or 0)
        except (TypeError, ValueError):
            return 0
    return 0


def _render_html(
    chat_name: str,
    messages: list[dict[str, Any]],
    media_map: dict[tuple[int, str], str],
) -> str:
    parts: list[str] = [
        "<!doctype html>",
        "<html><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width, initial-scale=1'>",
        f"<title>{html.escape(chat_name)}</title>",
        "<style>",
        "body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#17212b;color:#e6ebf0;margin:0}",
        ".wrap{max-width:960px;margin:0 auto;padding:16px}",
        ".header{position:sticky;top:0;background:#242f3d;padding:10px 14px;border-radius:10px;margin-bottom:12px}",
        ".msg{background:#242f3d;border-radius:12px;padding:10px 12px;margin:8px 0}",
        ".meta{font-size:12px;color:#8ca0b3;margin-bottom:6px;display:flex;gap:8px;flex-wrap:wrap}",
        ".name{font-weight:600;color:#6ab0ff}",
        ".txt{white-space:pre-wrap;line-height:1.45}",
        ".media{margin-top:8px;display:flex;flex-direction:column;gap:6px}",
        "img{max-width:100%;border-radius:8px}",
        "video,audio{max-width:100%}",
        "a{color:#66b3ff;text-decoration:none}",
        "</style></head><body><div class='wrap'>",
        f"<div class='header'><strong>{html.escape(chat_name)}</strong> · {len(messages)} 条消息</div>",
    ]
    for msg in messages:
        parts.append(_render_message(msg, media_map))
    parts.append("</div></body></html>")
    return "".join(parts)


def _render_message(
    msg: dict[str, Any],
    media_map: dict[tuple[int, str], str],
) -> str:
    mid = int(msg.get("id") or 0)
    from_name = html.escape(str(msg.get("from") or "Unknown"))
    date_unix = msg.get("date_unixtime")
    if date_unix is None:
        date_text = html.escape(str(msg.get("date") or ""))
    else:
        dt = datetime.fromtimestamp(int(date_unix), tz=timezone.utc).astimezone(UTC8)
        date_text = dt.strftime("%Y-%m-%d %H:%M:%S")
    text_val = extract_text(msg.get("text"))
    text_html = html.escape(text_val or "")

    media_nodes: list[str] = []
    for kind, rel in extract_media_refs(msg):
        abs_path = media_map.get((mid, rel))
        if not abs_path:
            continue
        uri = Path(abs_path).resolve().as_uri()
        rel_esc = html.escape(rel)
        if kind == "photo":
            media_nodes.append(f"<img loading='lazy' src='{uri}' alt='{rel_esc}'>")
        elif kind in ("video", "animation", "video_note"):
            media_nodes.append(f"<video controls preload='metadata' src='{uri}'></video>")
        elif kind in ("voice_message", "audio", "music"):
            media_nodes.append(f"<audio controls src='{uri}'></audio>")
        else:
            media_nodes.append(f"<a href='{uri}' target='_blank'>{rel_esc}</a>")
    media_html = ""
    if media_nodes:
        media_html = "<div class='media'>" + "".join(media_nodes) + "</div>"
    return (
        "<div class='msg'>"
        f"<div class='meta'><span class='name'>{from_name}</span><span>{date_text}</span></div>"
        f"<div class='txt'>{text_html}</div>"
        f"{media_html}"
        "</div>"
    )
