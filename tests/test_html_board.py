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


def test_render_photo_embeds_data_uri(tmp_path: Path) -> None:
    photos = tmp_path / "photos"
    photos.mkdir()
    img = photos / "pic.jpg"
    img.write_bytes(b"\xff\xd8\xff\xd8")
    (tmp_path / "css").mkdir()
    (tmp_path / "css" / "style.css").write_text("", encoding="utf-8")
    msg = {
        "id": 1,
        "type": "message",
        "date_unixtime": "1716199200",
        "from": "A",
        "from_id": "u1",
        "photo": "photos/pic.jpg",
    }
    media_map = {(1, "photos/pic.jpg"): str(img)}
    out = _render_native_html("Test", [msg], media_map, tmp_path)
    assert 'class="photo"' in out
    assert "data:image/jpeg;base64," in out
