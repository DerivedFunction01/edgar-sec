from __future__ import annotations

from edgar_sec.domain.forms.common.checkmarks import (
    CANONICAL_CHECKED,
    CANONICAL_UNCHECKED,
    CHECKMARK_MARK_RE,
    MARK_CHARACTERS,
    RE_FILLED_CHECKED,
    font_bullet_glyph_state,
    font_glyph_state,
    mark_token_state,
)


def test_canonical_constants() -> None:
    assert CANONICAL_CHECKED == "[X]"
    assert CANONICAL_UNCHECKED == "[ ]"


def test_font_glyph_state() -> None:
    assert font_glyph_state("Wingdings", "þ") == "checked"
    assert font_glyph_state("Wingdings", "ý") == "checked"
    assert font_glyph_state("Wingdings", "o") == "unchecked"
    assert font_glyph_state("Wingdings", "¨") == "unchecked"

    assert font_glyph_state("Wingdings 2", "R") == "unchecked"
    assert font_glyph_state("Wingdings 2", "S") == "checked"
    assert font_glyph_state("Wingdings 2", "£") == "checked"

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


def test_mark_token_state_recognizes_known_tokens() -> None:
    assert mark_token_state("[X]") == "checked"
    assert mark_token_state("(x)") == "checked"
    assert mark_token_state("☒") == "checked"
    assert mark_token_state("✘") == "checked"
    assert mark_token_state("&#9746;") == "checked"
    assert mark_token_state("[ ]") == "unchecked"
    assert mark_token_state("☐") == "unchecked"
    assert mark_token_state("&#9744;") == "unchecked"
    assert mark_token_state("not a mark") is None


def test_mark_token_state_recognizes_a_checked_fill() -> None:
    assert mark_token_state("___X____") == "checked"
    assert mark_token_state("___x____") == "checked"
    assert mark_token_state("X___") == "checked"


def test_mark_token_state_rejects_an_unfilled_run() -> None:
    assert mark_token_state("____") is None
    assert mark_token_state("_____") is None
    assert mark_token_state("____", allow_bare=True) is None


def test_mark_token_state_requires_context_for_a_bare_mark() -> None:
    assert mark_token_state("x") is None
    assert mark_token_state("X") is None
    assert mark_token_state("x", allow_bare=True) == "checked"
    assert mark_token_state("X", allow_bare=True) == "checked"


def test_filled_check_pattern_matches_only_a_symbol_in_a_slot() -> None:
    assert RE_FILLED_CHECKED.search("___X____") is not None
    assert RE_FILLED_CHECKED.search("X___") is not None
    assert RE_FILLED_CHECKED.search("____") is None
    assert RE_FILLED_CHECKED.search("tax___") is None


def test_mark_characters_cover_every_mark_glyph() -> None:
    for glyph in "☒☑✓✔✘☐□¨xXoOþýrR●■▪•&#9746;_-[](){}":
        assert glyph in MARK_CHARACTERS
