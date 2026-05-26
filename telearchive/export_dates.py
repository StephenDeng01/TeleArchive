"""Parse date/time boundaries and presets (UTC+8)."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

UTC8 = timezone(timedelta(hours=8))
ALL_FROM = "1970-01-01T00:00:00"
ALL_TO = "2099-12-31T23:59:59"

_BOUND_FORMATS = (
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d",
)


def parse_bound(value: str, *, end_of_day: bool = False) -> int:
    """
    Parse a boundary to Unix timestamp using UTC+8 (China local time).

    Accepts:
    - Unix seconds: ``1716199200``
    - Date: ``2026-05-20`` (start of day, or end if ``end_of_day``)
    - Date-time: ``2026-05-20T10:00:00`` or ``2026-05-20 10:00:00``
    """
    text = value.strip()
    if re.fullmatch(r"\d{9,12}", text):
        return int(text)

    normalized = text.replace(" ", "T")
    for fmt in _BOUND_FORMATS:
        try:
            dt = datetime.strptime(normalized, fmt)
            if fmt == "%Y-%m-%d" and end_of_day:
                dt = dt.replace(hour=23, minute=59, second=59)
            return int(dt.replace(tzinfo=UTC8).timestamp())
        except ValueError:
            continue

    raise ValueError(
        f"无法解析时间: {value!r}，请使用 YYYY-MM-DD、YYYY-MM-DDTHH:MM:SS 或 Unix 时间戳（UTC+8）"
    )


def set_shortcut_range(name: str, now: datetime | None = None) -> tuple[str, str]:
    """Return (from, to) strings with second precision in UTC+8."""
    ref = now.astimezone(UTC8) if now else datetime.now(UTC8)
    today = ref.date()
    end_today = datetime.combine(today, datetime.max.time()).replace(
        microsecond=0, tzinfo=UTC8
    )
    end_str = end_today.strftime("%Y-%m-%dT%H:%M:%S")

    if name == "today":
        start = datetime.combine(today, datetime.min.time()).replace(tzinfo=UTC8)
    elif name == "3d":
        start_day = today - timedelta(days=2)
        start = datetime.combine(start_day, datetime.min.time()).replace(tzinfo=UTC8)
    elif name == "7d":
        start_day = today - timedelta(days=6)
        start = datetime.combine(start_day, datetime.min.time()).replace(tzinfo=UTC8)
    elif name == "30d":
        start_day = today - timedelta(days=29)
        start = datetime.combine(start_day, datetime.min.time()).replace(tzinfo=UTC8)
    elif name == "all":
        return (ALL_FROM, ALL_TO)
    else:
        raise ValueError(f"未知快捷范围: {name}")

    return (start.strftime("%Y-%m-%dT%H:%M:%S"), end_str)


def default_datetime_bounds(now: datetime | None = None) -> tuple[str, str]:
    ref = now.astimezone(UTC8) if now else datetime.now(UTC8)
    text = ref.strftime("%Y-%m-%dT%H:%M:%S")
    return (text, text)
