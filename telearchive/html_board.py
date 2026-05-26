"""Build Telegram Desktop-style HTML previews for GUI board from merged DB messages."""

from __future__ import annotations

import base64
import html
import json
import mimetypes
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from telearchive.db import Database
from telearchive.export_dates import ALL_FROM, ALL_TO, UTC8, parse_bound
from telearchive.media import (
    extract_media_refs,
    is_raster_image_path,
    photo_thumb_relative,
)
from telearchive.parser import extract_text

# Bump when HTML/CSS rendering changes so stale html_cache bundles are rebuilt.
BOARD_RENDER_VERSION = "r3"
_MAX_EMBED_BYTES = 3 * 1024 * 1024
_MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)


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


def render_range_to_cache(
    db: Database,
    cache_dir: Path,
    chat_id: int,
    from_text: str,
    to_text: str,
) -> BoardRenderResult:
    from_ts = parse_bound(from_text, end_of_day=False)
    to_ts = parse_bound(to_text, end_of_day=True)
    if from_ts > to_ts:
        raise ValueError(f"开始时间不能晚于结束时间: {from_text} > {to_text}")

    chat = db.get_chat(chat_id)
    if chat is None:
        raise ValueError(f"数据库中不存在群聊 id={chat_id}")
    chat_name = str(chat["name"])

    key = f"chat_{chat_id}_{from_ts}_{to_ts}_{BOARD_RENDER_VERSION}"
    chat_dir = (cache_dir / f"chat_{chat_id}").resolve()
    bundle_dir = chat_dir / key
    json_path = bundle_dir / "board_meta.json"
    html_path = bundle_dir / "messages.html"
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

    if bundle_dir.exists():
        shutil.rmtree(bundle_dir, ignore_errors=True)
    bundle_dir.mkdir(parents=True, exist_ok=True)
    _install_tg_assets(bundle_dir)

    message_ids = [int(m["id"]) for m in messages if m.get("id") is not None]
    media_map = db.fetch_media_sources(chat_id, message_ids)
    _copy_media_files(bundle_dir, messages, media_map)

    html_path.write_text(
        _render_native_html(chat_name, messages, media_map, bundle_dir),
        encoding="utf-8",
    )
    json_path.write_text(
        json.dumps(
            {
                "chat_id": chat_id,
                "chat_name": chat_name,
                "from_ts": from_ts,
                "to_ts": to_ts,
                "message_count": len(messages),
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


def _tg_assets_root() -> Path:
    return Path(__file__).resolve().parent / "assets" / "tg_export"


def _install_tg_assets(bundle_dir: Path) -> None:
    src = _tg_assets_root()
    for sub in ("css", "js"):
        dest = bundle_dir / sub
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(src / sub, dest)


def _copy_media_files(
    bundle_dir: Path,
    messages: list[dict[str, Any]],
    media_map: dict[tuple[int, str], str],
) -> None:
    seen: set[str] = set()
    for msg in messages:
        mid = msg.get("id")
        if mid is None:
            continue
        for kind, rel in extract_media_refs(msg):
            if rel in seen:
                continue
            seen.add(rel)
            src = media_map.get((int(mid), rel))
            if not src:
                if kind == "thumbnail":
                    for _k, photo_rel in extract_media_refs(msg):
                        if _k != "photo":
                            continue
                        photo_src = media_map.get((int(mid), photo_rel))
                        if not photo_src:
                            continue
                        thumb_src = Path(photo_src).parent / Path(
                            photo_thumb_relative(photo_rel)
                        ).name
                        if thumb_src.is_file():
                            src = str(thumb_src)
                        break
                if not src:
                    continue
            src_path = Path(src)
            if not src_path.is_file():
                continue
            dest = bundle_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            if not dest.exists():
                shutil.copy2(src_path, dest)


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


def _read_bundle_css(bundle_dir: Path) -> str:
    css_path = bundle_dir / "css" / "style.css"
    if not css_path.is_file():
        return ""
    return css_path.read_text(encoding="utf-8")


def _render_native_html(
    chat_name: str,
    messages: list[dict[str, Any]],
    media_map: dict[tuple[int, str], str],
    bundle_dir: Path,
) -> str:
    title = html.escape(chat_name)
    history = _render_history(messages, media_map, bundle_dir)
    css = _read_bundle_css(bundle_dir)
    style_block = f"  <style>\n{css}\n  </style>\n" if css else ""
    return (
        "<!DOCTYPE html>\n<html>\n <head>\n"
        "  <meta charset=\"utf-8\"/>\n"
        f"<title>{title}</title>\n"
        "  <meta content=\"width=device-width, initial-scale=1.0\" name=\"viewport\"/>\n"
        f"{style_block}"
        "  <link href=\"css/style.css\" rel=\"stylesheet\"/>\n"
        "  <script src=\"js/script.js\" type=\"text/javascript\">\n  </script>\n"
        " </head>\n"
        " <body onload=\"CheckLocation();\">\n"
        "  <div class=\"page_wrap\">\n"
        "   <div class=\"page_header\">\n"
        "    <div class=\"content\">\n"
        f"     <div class=\"text bold\">\n{title}\n     </div>\n"
        "    </div>\n"
        "   </div>\n"
        "   <div class=\"page_body chat_page\">\n"
        "    <div class=\"history\">\n"
        f"{history}"
        "    </div>\n"
        "   </div>\n"
        "  </div>\n"
        " </body>\n</html>\n"
    )


def _render_history(
    messages: list[dict[str, Any]],
    media_map: dict[tuple[int, str], str],
    bundle_dir: Path,
) -> str:
    parts: list[str] = []
    prev_day: datetime.date | None = None
    prev_from_id: str | None = None
    day_counter = 0

    for msg in messages:
        msg_type = str(msg.get("type") or "message")
        if msg_type == "service":
            parts.append(_render_service_message(msg))
            prev_from_id = None
            continue

        dt = _msg_datetime(msg)
        if dt is not None and (prev_day is None or dt.date() != prev_day):
            day_counter += 1
            parts.append(_render_date_separator(dt, day_counter))
            prev_day = dt.date()
            prev_from_id = None

        from_id = str(msg.get("from_id") or "")
        joined = bool(from_id and from_id == prev_from_id)
        parts.append(
            _render_default_message(msg, media_map, bundle_dir, joined=joined)
        )
        prev_from_id = from_id if from_id else None

    return "".join(parts)


def _render_date_separator(dt: datetime, counter: int) -> str:
    label = f"{dt.day} {_MONTHS[dt.month - 1]} {dt.year}"
    return (
        f"     <div class=\"message service\" id=\"message-day-{counter}\">\n"
        "      <div class=\"body details\">\n"
        f"{html.escape(label)}\n"
        "      </div>\n"
        "     </div>\n\n"
    )


def _render_service_message(msg: dict[str, Any]) -> str:
    mid = int(msg.get("id") or 0)
    body = extract_text(msg.get("text")) or str(msg.get("action") or "")
    return (
        f"     <div class=\"message service\" id=\"message{mid}\">\n"
        "      <div class=\"body details\">\n"
        f"{html.escape(body)}\n"
        "      </div>\n"
        "     </div>\n\n"
    )


def _render_default_message(
    msg: dict[str, Any],
    media_map: dict[tuple[int, str], str],
    bundle_dir: Path,
    *,
    joined: bool,
) -> str:
    mid = int(msg.get("id") or 0)
    dt = _msg_datetime(msg)
    time_label = dt.strftime("%H:%M") if dt else ""
    title = _date_title(dt) if dt else ""
    from_name = html.escape(str(msg.get("from") or "Unknown"))
    from_id = str(msg.get("from_id") or from_name)
    pic_idx = _userpic_index(from_id)
    initials = _initials(str(msg.get("from") or "?"))

    joined_cls = " joined" if joined else ""
    lines: list[str] = [
        f"     <div class=\"message default clearfix{joined_cls}\" id=\"message{mid}\">\n",
    ]
    if not joined:
        lines.extend(
            [
                "      <div class=\"pull_left userpic_wrap\">\n",
                f"       <div class=\"userpic userpic{pic_idx}\" style=\"width: 42px; height: 42px\">\n",
                f"        <div class=\"initials\" style=\"line-height: 42px\">\n{html.escape(initials)}\n",
                "        </div>\n",
                "       </div>\n",
                "      </div>\n",
            ]
        )
    lines.append("      <div class=\"body\">\n")
    if title:
        lines.append(
            f"       <div class=\"pull_right date details\" title=\"{html.escape(title)}\">\n"
            f"{html.escape(time_label)}\n"
            "       </div>\n"
        )
    if not joined:
        lines.append(
            f"       <div class=\"from_name\">\n{from_name} \n       </div>\n"
        )

    reply_id = msg.get("reply_to_message_id")
    if reply_id is not None:
        lines.append(
            "       <div class=\"reply_to details\">\n"
            f"In reply to <a href=\"#go_to_message{int(reply_id)}\" "
            f"onclick=\"return GoToMessage({int(reply_id)})\">this message</a>\n"
            "       </div>\n"
        )

    text_html = _format_text_html(msg.get("text"))
    if text_html and not _text_is_redundant_media_path(msg):
        lines.append(f"       <div class=\"text\">\n{text_html}\n       </div>\n")

    lines.extend(_render_media_blocks(msg, media_map, bundle_dir))
    lines.extend(_render_reactions(msg))
    lines.append("      </div>\n")
    lines.append("     </div>\n\n")
    return "".join(lines)


def _bundle_file(bundle_dir: Path, rel: str, media_map: dict[tuple[int, str]], mid: int) -> Path | None:
    local = bundle_dir / rel
    if local.is_file():
        return local
    remote = media_map.get((mid, rel))
    if remote and Path(remote).is_file():
        return Path(remote)
    return None


def _image_src_attr(path: Path) -> str:
    embedded = _embed_image_data_uri(path)
    if embedded:
        return embedded
    return html.escape(path.as_uri(), quote=True)


def _embed_image_data_uri(path: Path) -> str | None:
    if not path.is_file() or not is_raster_image_path(path.name):
        return None
    try:
        size = path.stat().st_size
    except OSError:
        return None
    if size > _MAX_EMBED_BYTES:
        return None
    mime, _ = mimetypes.guess_type(path.name)
    if not mime or not mime.startswith("image/"):
        mime = "image/jpeg"
    try:
        payload = base64.standard_b64encode(path.read_bytes()).decode("ascii")
    except OSError:
        return None
    return f"data:{mime};base64,{payload}"


def _text_is_redundant_media_path(msg: dict[str, Any]) -> bool:
    paths = {rel for _kind, rel in extract_media_refs(msg)}
    text = extract_text(msg.get("text")).strip()
    return bool(text and text in paths)


def _render_reactions(msg: dict[str, Any]) -> list[str]:
    raw = msg.get("reactions")
    if not isinstance(raw, list) or not raw:
        return []
    items: list[str] = []
    for reaction in raw:
        if not isinstance(reaction, dict):
            continue
        emoji = str(reaction.get("emoji") or "").strip()
        if not emoji:
            continue
        count = reaction.get("count")
        count_html = ""
        if count is not None:
            try:
                count_html = f"\n         <span class=\"count\">\n{int(count)}\n         </span>\n"
            except (TypeError, ValueError):
                pass
        items.append(
            "        <span class=\"reaction\">\n"
            f"         <span class=\"emoji\">\n{html.escape(emoji)}\n         </span>\n"
            f"{count_html}"
            "        </span>\n"
        )
    if not items:
        return []
    return [
        "       <span class=\"reactions\">\n",
        *items,
        "       </span>\n",
    ]


def _render_media_blocks(
    msg: dict[str, Any],
    media_map: dict[tuple[int, str], str],
    bundle_dir: Path,
) -> list[str]:
    mid = int(msg.get("id") or 0)
    blocks: list[str] = []
    rendered_photos: set[str] = set()
    for kind, rel in extract_media_refs(msg):
        if kind == "thumbnail":
            continue
        if kind == "photo":
            if rel in rendered_photos:
                continue
            rendered_photos.add(rel)
            thumb_rel = photo_thumb_relative(rel)
            display_rel = thumb_rel
            display_path = _bundle_file(bundle_dir, thumb_rel, media_map, mid)
            full_path = _bundle_file(bundle_dir, rel, media_map, mid)
            if display_path is None:
                display_rel = rel
                display_path = full_path
            if display_path is None:
                continue
            href_path = full_path or display_path
            href_esc = html.escape(href_path.as_uri(), quote=True)
            src_esc = _image_src_attr(display_path)
            blocks.extend(
                [
                    "       <div class=\"media_wrap clearfix\">\n",
                    f"        <a class=\"photo_wrap clearfix pull_left\" href=\"{href_esc}\">\n",
                    f"         <img class=\"photo\" src=\"{src_esc}\" "
                    "style=\"width: 260px; height: auto\"/>\n",
                    "        </a>\n",
                    "       </div>\n",
                ]
            )
            continue
        file_path = _bundle_file(bundle_dir, rel, media_map, mid)
        if file_path is None:
            continue
        rel_esc = html.escape(rel)
        if kind == "sticker" and is_raster_image_path(rel):
            src_esc = _image_src_attr(file_path)
            blocks.extend(
                [
                    "       <div class=\"media_wrap clearfix\">\n",
                    f"        <img class=\"sticker\" src=\"{src_esc}\" "
                    "style=\"max-width: 260px; height: auto\"/>\n",
                    "       </div>\n",
                ]
            )
        elif kind in ("video", "animation", "video_note"):
            src_esc = html.escape(file_path.as_uri(), quote=True)
            blocks.extend(
                [
                    "       <div class=\"media_wrap clearfix\">\n",
                    f"        <video class=\"video_file\" controls preload=\"metadata\" "
                    f"src=\"{src_esc}\"></video>\n",
                    "       </div>\n",
                ]
            )
        elif kind in ("voice_message", "audio", "music"):
            src_esc = html.escape(file_path.as_uri(), quote=True)
            blocks.extend(
                [
                    "       <div class=\"media_wrap clearfix\">\n",
                    f"        <audio controls src=\"{src_esc}\"></audio>\n",
                    "       </div>\n",
                ]
            )
        elif is_raster_image_path(rel):
            src_esc = _image_src_attr(file_path)
            blocks.extend(
                [
                    "       <div class=\"media_wrap clearfix\">\n",
                    f"        <img class=\"photo\" src=\"{src_esc}\" "
                    "style=\"max-width: 260px; height: auto\"/>\n",
                    "       </div>\n",
                ]
            )
        else:
            blocks.extend(
                [
                    "       <div class=\"media_wrap clearfix\">\n",
                    f"        <a href=\"{rel_esc}\">{rel_esc}</a>\n",
                    "       </div>\n",
                ]
            )
    return blocks


def _format_text_html(raw: Any) -> str:
    if raw is None:
        return ""
    if isinstance(raw, str):
        return html.escape(raw).replace("\n", "<br>")
    if not isinstance(raw, list):
        return html.escape(str(raw))

    parts: list[str] = []
    for item in raw:
        if isinstance(item, str):
            parts.append(html.escape(item).replace("\n", "<br>"))
            continue
        if not isinstance(item, dict):
            continue
        entity_type = str(item.get("type") or "plain")
        text = str(item.get("text") or "")
        escaped = html.escape(text).replace("\n", "<br>")
        if entity_type == "link":
            href = html.escape(text, quote=True)
            parts.append(f'<a href="{href}">{escaped}</a>')
        elif entity_type == "bold":
            parts.append(f"<strong>{escaped}</strong>")
        elif entity_type == "italic":
            parts.append(f"<em>{escaped}</em>")
        elif entity_type == "underline":
            parts.append(f"<u>{escaped}</u>")
        elif entity_type == "strikethrough":
            parts.append(f"<s>{escaped}</s>")
        elif entity_type == "code":
            parts.append(f"<code>{escaped}</code>")
        elif entity_type == "pre":
            parts.append(f"<pre>{escaped}</pre>")
        elif entity_type == "spoiler":
            parts.append(f'<span class="spoiler hidden">{escaped}</span>')
        elif entity_type in ("custom_emoji", "emoji"):
            parts.append(f'<span class="emoji">{escaped}</span>')
        else:
            parts.append(escaped)
    return "".join(parts)


def _msg_datetime(msg: dict[str, Any]) -> datetime | None:
    raw = msg.get("date_unixtime")
    if raw is None:
        return None
    try:
        return datetime.fromtimestamp(int(raw), tz=timezone.utc).astimezone(UTC8)
    except (TypeError, ValueError):
        return None


def _date_title(dt: datetime) -> str:
    return dt.strftime("%d.%m.%Y %H:%M:%S UTC+08:00")


def _userpic_index(from_id: str) -> int:
    return (sum(ord(ch) for ch in from_id) % 8) + 1


def _initials(name: str) -> str:
    name = name.strip()
    if not name:
        return "?"
    chunks = name.split()
    if len(chunks) >= 2:
        return (chunks[0][:1] + chunks[1][:1]).upper()
    if len(name) >= 2:
        return name[:2]
    return name[:1]
