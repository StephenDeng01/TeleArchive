"""Local user preferences (update reminders, etc.)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DEFAULT_SETTINGS_PATH = Path("data/settings.json")


def settings_path(path: Path | None = None) -> Path:
    return path or DEFAULT_SETTINGS_PATH


def load_settings(path: Path | None = None) -> dict[str, Any]:
    target = settings_path(path)
    if not target.is_file():
        return {}
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_settings(data: dict[str, Any], path: Path | None = None) -> None:
    target = settings_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def get_dismissed_update_version(path: Path | None = None) -> str | None:
    value = load_settings(path).get("dismissed_update_version")
    return str(value) if value else None


def set_dismissed_update_version(version: str, path: Path | None = None) -> None:
    data = load_settings(path)
    data["dismissed_update_version"] = version
    save_settings(data, path)
