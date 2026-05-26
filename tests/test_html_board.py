from pathlib import Path

from telearchive.html_board import (
    BOARD_RENDER_VERSION,
    _format_text_html,
    _initials,
    _render_native_html,
    _userpic_index,
)


def test_format_text_html_link() -> None:
    raw = [{"type": "link", "text": "https://example.com"}]
    out = _format_text_html(raw)
    assert 'href="https://example.com"' in out
    assert "https://example.com" in out


def test_userpic_index_stable() -> None:
    assert 1 <= _userpic_index("user123") <= 8
    assert _userpic_index("user123") == _userpic_index("user123")


def test_initials() -> None:
    assert _initials("Alice Bob") == "AB"
    assert _initials("周小琪") == "周小"


def test_render_native_html_inlines_css(tmp_path: Path) -> None:
    css_dir = tmp_path / "css"
    css_dir.mkdir()
    (css_dir / "style.css").write_text(".userpic { color: red; }", encoding="utf-8")
    out = _render_native_html("Test", [], {}, tmp_path)
    assert "<style>" in out
    assert ".userpic { color: red; }" in out
    assert BOARD_RENDER_VERSION.startswith("r")
