"""Parse date/time arguments for range export."""

from __future__ import annotations

import re
from datetime import datetime, timezone


def parse_bound(value: str, *, end_of_day: bool = False) -> int:
    """
    Parse a boundary to unix timestamp (UTC).

    Accepts:
    - Unix seconds: ``1716199200``
    - Date: ``2026-05-20``
    - Date-time: ``2026-05-20T10:00:00`` or ``2026-05-20 10:00:00``
    """
    text = value.strip()
    if re.fullmatch(r"\d{9,12}", text):
        return int(text)

    normalized = text.replace(" ", "T")
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(normalized, fmt)
            if fmt == "%Y-%m-%d" and end_of_day:
                dt = dt.replace(hour=23, minute=59, second=59)
            return int(dt.replace(tzinfo=timezone.utc).timestamp())
        except ValueError:
            continue

    raise ValueError(
        f"无法解析时间: {value!r}，请使用 YYYY-MM-DD 或 YYYY-MM-DDTHH:MM:SS 或 Unix 时间戳"
    )
