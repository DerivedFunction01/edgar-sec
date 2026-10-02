"""Unit tests for edgar_sec.domain.forms.common.checkmarks."""

from __future__ import annotations

from edgar_sec.domain.forms.common.checkmarks import (
    CANONICAL_CHECKED,
    CANONICAL_UNCHECKED,
    CHECKMARK_MARK_RE,
    font_bullet_glyph_state,
    font_glyph_state,
)


def test_canonical_constants() -> None:
    assert CANONICAL_CHECKED == "[X]"
    assert CANONICAL_UNCHECKED == "[ ]"


def test_font_glyph_state() -> None:
    # Wingdings checkbox glyphs
    assert font_glyph_state("Wingdings", "þ") == "checked"
    assert font_glyph_state("Wingdings", "ý") == "checked"
    assert font_glyph_state("Wingdings", "o") == "unchecked"
    assert font_glyph_state("Wingdings", "¨") == "unchecked"

    # Wingdings 2 checkbox glyphs
    assert font_glyph_state("Wingdings 2", "R") == "unchecked"
    assert font_glyph_state("Wingdings 2", "S") == "checked"
    assert font_glyph_state("Wingdings 2", "£") == "checked"

    # Unknown or non-matching font
    assert font_glyph_state("Arial", "x") is None
    assert font_glyph_state("Wingdings", "Z") is None


def test_font_bullet_glyph_state() -> None:
    assert font_bullet_glyph_state("Wingdings", "n") == "•"
    assert font_bullet_glyph_state("Wingdings", "u") == "○"
    assert font_bullet_glyph_state("Arial", "a") is None


def test_checkmark_mark_re() -> None:
    assert CHECKMARK_MARK_RE.search("[X]") is not None
    assert CHECKMARK_MARK_RE.search("[x]") is not None
    assert CHECKMARK_MARK_RE.search("[ ]") is not None
    assert CHECKMARK_MARK_RE.search("[_]") is not None
    assert CHECKMARK_MARK_RE.search("(X)") is not None
    assert CHECKMARK_MARK_RE.search("( )") is not None
    assert CHECKMARK_MARK_RE.search("☒") is not None
    assert CHECKMARK_MARK_RE.search("☐") is not None
