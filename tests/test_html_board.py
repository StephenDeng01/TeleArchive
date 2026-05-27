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


def test_render_native_html_uses_tg_assets(tmp_path: Path) -> None:
    css_dir = tmp_path / "css"
    css_dir.mkdir()
    (css_dir / "style.css").write_text(".userpic { color: red; }", encoding="utf-8")
    js_dir = tmp_path / "js"
    js_dir.mkdir()
    (js_dir / "script.js").write_text("", encoding="utf-8")
    out = _render_native_html("Test", [], {}, tmp_path)
    assert 'href="css/style.css"' in out
    assert 'src="js/script.js"' in out
    assert BOARD_RENDER_VERSION.startswith("r")


def test_render_photo_uses_relative_paths(tmp_path: Path) -> None:
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
        "width": 1280,
        "height": 720,
    }
    media_map = {(1, "photos/pic.jpg"): str(img)}
    out = _render_native_html("Test", [msg], media_map, tmp_path)
    assert 'class="photo"' in out
    assert 'src="photos/pic.jpg"' in out
    assert "data:image" not in out


def test_render_sticker_native_markup(tmp_path: Path) -> None:
    stickers = tmp_path / "stickers"
    stickers.mkdir()
    img = stickers / "sticker.webp"
    img.write_bytes(b"RIFF")
    (tmp_path / "css").mkdir()
    (tmp_path / "css" / "style.css").write_text("", encoding="utf-8")
    msg = {
        "id": 2,
        "type": "message",
        "date_unixtime": "1716199200",
        "from": "B",
        "from_id": "u2",
        "file": "stickers/sticker.webp",
        "media_type": "sticker",
        "width": 512,
        "height": 512,
    }
    media_map = {(2, "stickers/sticker.webp"): str(img)}
    out = _render_native_html("Test", [msg], media_map, tmp_path)
    assert "sticker_wrap" in out
    assert 'href="stickers/sticker.webp"' in out
