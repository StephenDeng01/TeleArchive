"""Allow ``python -m telearchive`` and PyInstaller entry."""

from telearchive.cli import app

if __name__ == "__main__":
    app()
