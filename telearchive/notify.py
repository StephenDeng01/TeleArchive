"""Best-effort desktop notifications (supplement to in-app dialogs)."""

from __future__ import annotations

import platform
import subprocess


def notify_update_available(title: str, message: str) -> bool:
    """
    Show a system notification when possible.

    Returns True if a notification was attempted on the current platform.
    """
    system = platform.system()
    if system == "Darwin":
        script = (
            f'display notification "{_escape_applescript(message)}" '
            f'with title "{_escape_applescript(title)}"'
        )
        subprocess.run(["osascript", "-e", script], check=False, capture_output=True)
        return True
    return False


def _escape_applescript(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')
