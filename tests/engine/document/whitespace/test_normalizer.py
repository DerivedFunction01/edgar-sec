"""Tests for final-text whitespace normalization.

Re-lands the suite deleted in commit `079010e` and extends it to the
punctuation gating that keeps column separators from being read as list
boundaries — the failure mode this pass exists to avoid.
"""

from __future__ import annotations

from edgar_sec.engine.document.whitespace.normalizer import (
    normalize_final_text_whitespace,
    split_concatenated_bullets,
)

TABLE = "<TABLE>\n<TR><TD>  A  </TD><TD>\tB\t</TD></TR>\n</TABLE>"


def test_empty_text() -> None:
    assert normalize_final_text_whitespace("") == ""
    assert split_concatenated_bullets("") == ""


def test_strips_line_end_padding() -> None:
    # Trailing newlines are preserved: this stage normalizes, it does not
    # truncate. The pipeline's final strip owns the outer edges.
    assert normalize_final_text_whitespace("a   \nb\t\n") == "a\nb\n"


def test_collapses_excessive_blank_lines() -> None:
    assert normalize_final_text_whitespace("a\n\n\n\n\nb") == "a\n\nb"


def test_keeps_a_single_blank_line() -> None:
    assert normalize_final_text_whitespace("a\n\nb") == "a\n\nb"


def test_splits_concatenated_bullets() -> None:
    text = "Revenue grew; and - costs fell; • margins improved"
    result = normalize_final_text_whitespace(text)
    assert result == "Revenue grew; and\n- costs fell;\n• margins improved"


def test_splits_glyph_bullets_after_a_period() -> None:
    result = split_concatenated_bullets("First item. • second item. • third item")
    assert result.count("\n") >= 2
    assert "• second item" in result


def test_splits_footnote_markers() -> None:
    result = split_concatenated_bullets("See the filing. * 1 Note one; * 2 Note two")
    assert "\n" in result
    assert "* 1 Note one" in result


def test_does_not_split_inside_a_sentence() -> None:
    """A period followed by an ordinary word is prose, not a list boundary."""
    assert split_concatenated_bullets("The value was 3.5 for the period") == (
        "The value was 3.5 for the period"
    )


def test_does_not_split_at_a_trailing_colon() -> None:
    assert split_concatenated_bullets("The following items apply:") == (
        "The following items apply:"
    )


def test_table_spacing_survives_byte_for_byte() -> None:
    payload = f"intro line   \n{TABLE}\ntrailing   "
    result = normalize_final_text_whitespace(payload)
    assert TABLE in result
    assert result.startswith("intro line\n")


def test_split_bullets_preserves_table() -> None:
    result = split_concatenated_bullets(f"a; and b\n{TABLE}")
    assert TABLE in result


def test_table_content_is_never_split() -> None:
    """Bullet splitting skips any line carrying a table sentinel."""
    text = f"{TABLE}"
    result = split_concatenated_bullets(f"one; two\n{text}")
    assert TABLE in result


def test_text_without_list_separators_is_unchanged() -> None:
    text = "A single sentence of ordinary prose."
    assert normalize_final_text_whitespace(text) == text
