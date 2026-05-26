from telearchive.html_board import _format_text_html, _initials, _userpic_index


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
