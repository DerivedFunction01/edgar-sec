"""Tests for final-text whitespace normalization."""

from __future__ import annotations

from edgar_sec.engine.document.whitespace import (
    count_lines,
    normalize_final_text_whitespace,
    split_concatenated_bullets,
)

TABLE = "<TABLE>\n<TR><TD>  A  </TD><TD>\tB\t</TD></TR>\n</TABLE>"


def test_strips_line_end_padding() -> None:
    # Trailing newlines are preserved: this stage normalizes, it does not
    # truncate. The pipeline's final ``.strip()`` owns the outer edges.
    assert normalize_final_text_whitespace("a   \nb\t\n") == "a\nb\n"


def test_collapses_excessive_blank_lines() -> None:
    assert normalize_final_text_whitespace("a\n\n\n\n\nb") == "a\n\nb"


def test_splits_concatenated_bullets() -> None:
    text = "Revenue grew; and - costs fell; \u2022 margins improved"
    result = normalize_final_text_whitespace(text)
    assert result == "Revenue grew; and\n- costs fell;\n\u2022 margins improved"


def test_table_spacing_survives_byte_for_byte() -> None:
    payload = f"intro line   \n{TABLE}\ntrailing   "
    result = normalize_final_text_whitespace(payload)
    assert TABLE in result
    assert result.startswith("intro line\n")


def test_split_bullets_preserves_table() -> None:
    result = split_concatenated_bullets(f"a; and b\n{TABLE}")
    assert TABLE in result


def test_empty_text() -> None:
    assert normalize_final_text_whitespace("") == ""
    assert split_concatenated_bullets("") == ""
    assert count_lines("") == 0


def test_count_lines_matches_splitlines() -> None:
    for text in ("a", "a\nb", "a\nb\n", "\n\n"):
        assert count_lines(text) == len(text.splitlines())
