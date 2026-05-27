"""Entry point: Qt GUI by default, CLI when arguments are provided."""

from __future__ import annotations

import sys

from telearchive.frozen_runtime import cleanup_stale_pyi_extracts


def should_launch_gui(argv: list[str] | None = None) -> bool:
    """True when the app should open the desktop UI instead of the CLI."""
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        return True
    if args == ["--gui"] or args == ["gui"]:
        return True
    return False


def main() -> None:
    cleanup_stale_pyi_extracts()
    argv = sys.argv[1:]
    if argv[:1] == ["--cli"]:
        argv = argv[1:]

    if should_launch_gui(argv):
        from telearchive.gui_qt import launch_qt_gui

        launch_qt_gui()
        return

    sys.argv = [sys.argv[0], *argv]
    from telearchive.cli import app

    app()


if __name__ == "__main__":
    main()
