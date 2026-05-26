"""Content hashing and attachment resolution for export media files."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


_HASH_CHUNK = 1024 * 1024


@dataclass(frozen=True)
class MediaAttachment:
    """A media file referenced in JSON, stored on disk beside result.json."""

    kind: str
    relative_path: str
    absolute_path: Path
    exists: bool
    size_bytes: int | None
    content_hash: str | None


def extract_media_refs(msg: dict[str, Any]) -> list[tuple[str, str]]:
    """
    Pull (kind, relative_path) pairs from a message object.

    Telegram JSON only stores paths like ``photos/photo_1@....jpg``;
    the bytes live in sibling folders under the export root.
    """
    refs: list[tuple[str, str]] = []
    seen: set[str] = set()

    def add(kind: str, path: Any) -> None:
        if not isinstance(path, str):
            return
        p = path.strip()
        if not p or p in seen:
            return
        seen.add(p)
        refs.append((kind, p))

    photo = msg.get("photo")
    add("photo", photo)
    add("thumbnail", msg.get("thumbnail"))
    if isinstance(photo, str) and photo.strip():
        add("thumbnail", photo_thumb_relative(photo.strip()))
    add("sticker", msg.get("sticker"))
    add("contact_vcard", msg.get("contact_vcard"))
    add("media", msg.get("media"))

    file_path = msg.get("file")
    if isinstance(file_path, str) and file_path.strip():
        kind = msg.get("media_type")
        add(str(kind) if kind else "file", file_path.strip())

    return refs


def photo_thumb_relative(photo_rel: str) -> str:
    path = Path(photo_rel)
    return str(path.with_name(f"{path.stem}_thumb{path.suffix}"))


def is_raster_image_path(path: str) -> bool:
    return Path(path).suffix.lower() in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}


def file_content_hash(path: Path) -> str | None:
    """SHA-256 of file contents; None if the file is missing."""
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_HASH_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def _path_inside_root(path: Path, root: Path) -> bool:
    """Reject path traversal (e.g. ../../outside/file) outside export_root."""
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def resolve_attachments(
    export_root: Path,
    msg: dict[str, Any],
) -> list[MediaAttachment]:
    """Resolve relative paths against the export folder that contains result.json."""
    root = export_root.resolve()
    out: list[MediaAttachment] = []
    for kind, rel in extract_media_refs(msg):
        absolute = (root / rel).resolve()
        if not _path_inside_root(absolute, root):
            continue
        exists = absolute.is_file()
        size = absolute.stat().st_size if exists else None
        content_hash = file_content_hash(absolute) if exists else None
        out.append(
            MediaAttachment(
                kind=kind,
                relative_path=rel,
                absolute_path=absolute,
                exists=exists,
                size_bytes=size,
                content_hash=content_hash,
            )
        )
    return out
