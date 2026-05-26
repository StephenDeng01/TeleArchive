"""Entry point: GUI by default, CLI when arguments are provided."""

from __future__ import annotations

import sys

from telearchive.gui import launch_gui, should_launch_gui


def main() -> None:
    argv = sys.argv[1:]
    if argv[:1] == ["--cli"]:
        argv = argv[1:]

    if should_launch_gui(argv):
        launch_gui()
        return

    sys.argv = [sys.argv[0], *argv]
    from telearchive.cli import app

    app()


if __name__ == "__main__":
    main()
