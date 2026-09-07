from __future__ import annotations

from defs.text import normalize_final_text_whitespace


def test_normalize_final_text_whitespace() -> None:
    text = "First  \nSecond\n\n\n\nThird\t\n"

    assert normalize_final_text_whitespace(text) == "First\nSecond\n\nThird\n"
