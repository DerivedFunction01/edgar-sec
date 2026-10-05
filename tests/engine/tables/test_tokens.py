"""Cell attachment vocabulary: prefix, suffix, range, and numeric cell starts."""

from __future__ import annotations

import pytest

from edgar_sec.engine.tables.tokens import (
    CLOSING_DELIMITERS,
    is_numeric_cell,
    is_prefix_token,
    is_range_marker,
    is_suffix_token,
    numeric_cell_starts,
)


@pytest.mark.parametrize("value", ["$", "€", "£", "("])
def test_prefix_tokens_attach_forward(value: str) -> None:
    assert is_prefix_token(value) is True


@pytest.mark.parametrize("value", ["%", "pt", "bps", ")", "]", "}"])
def test_suffix_tokens_attach_backward(value: str) -> None:
    assert is_suffix_token(value) is True


def test_suffix_matching_is_case_folded_but_prefix_is_not() -> None:
    assert is_suffix_token("YEARS") is True
    assert is_prefix_token("(") is True
    assert is_prefix_token("Revenue") is False


def test_closing_delimiters_are_suffix_tokens() -> None:
    assert CLOSING_DELIMITERS <= {")", "]", "}"}
    assert all(is_suffix_token(token) for token in CLOSING_DELIMITERS)


@pytest.mark.parametrize("value", ["-", "–", "to", "through", "thru"])
def test_range_markers(value: str) -> None:
    assert is_range_marker(value) is True


def test_range_marker_does_not_match_a_value() -> None:
    assert is_range_marker("1 - 5") is False


def test_numeric_cell_starts_finds_amounts_after_column_gaps() -> None:
    line = "Revenue          1,200          1,100"
    starts = numeric_cell_starts(line)
    assert len(starts) == 2
    assert line[starts[0] :].startswith("1,200")
    assert line[starts[1] :].startswith("1,100")


def test_numeric_cell_starts_finds_page_cells_after_dot_leaders() -> None:
    line = "Consolidated statements of operations ............    14"
    starts = numeric_cell_starts(line)
    assert len(starts) == 1
    assert line[starts[0] :].startswith("14")


def test_numeric_cell_starts_falls_back_to_a_content_indent() -> None:
    line = "  $1,234"
    starts = numeric_cell_starts(line)
    assert len(starts) == 1
    assert line[starts[0] :].startswith("$1,234")


def test_numeric_cell_starts_ignores_a_prose_lead() -> None:
    assert numeric_cell_starts("Total revenue 1,200") == ()


def test_tokens_module_re_exports_the_numeric_grammar() -> None:
    assert is_numeric_cell("1,000") is True
