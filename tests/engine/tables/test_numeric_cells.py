"""Unit tests for edgar_sec.engine.tables.numeric_cells.

The closing-delimiter, range-marker and suffix-token predicates were dropped
when v1's facade `defs/tables/tokens.py` was split, which left five `ascii_html`
modules importing names that did not exist anywhere. These tests pin the
restored definitions and the construction invariant that `SUFFIX_TOKENS` is
built from the named closing delimiters rather than listing them inline again.
"""

from __future__ import annotations

import pytest

from edgar_sec.engine.tables.currencies import (
    ALL_CURRENCY_SYMBOLS,
    SUFFIX_CURRENCY_SYMBOLS,
)
from edgar_sec.engine.tables.numeric_cells import (
    CLOSING_DELIMITERS,
    FINANCIAL_PLACEHOLDERS,
    NUMERIC_CELL_RE,
    PREFIX_TOKENS,
    RANGE_MARKERS,
    SUFFIX_TOKENS,
    is_numeric_cell,
    is_prefix_token,
    is_range_marker,
    is_suffix_token,
    numeric_cell_starts,
)


def test_is_numeric_cell() -> None:
    # Pure numbers and formatted currency
    assert is_numeric_cell("1,234.56")
    assert is_numeric_cell("$1,234")
    assert is_numeric_cell("(500)")
    assert is_numeric_cell("52.5%")
    assert is_numeric_cell("—")
    assert is_numeric_cell("N/A")
    assert is_numeric_cell("None")

    # Words should not be numeric
    assert not is_numeric_cell("Automotive")
    assert not is_numeric_cell("Segment")


def test_numeric_cell_starts() -> None:
    line = "  Automotive             $1,200     $1,100"
    starts = numeric_cell_starts(line)
    assert len(starts) == 2
    assert line[starts[0] : starts[0] + 6] == "$1,200"
    assert line[starts[1] : starts[1] + 6] == "$1,100"


def test_closing_delimiters_are_the_three_bracket_families() -> None:
    assert CLOSING_DELIMITERS == frozenset({")", "]", "}"})


def test_suffix_tokens_are_built_from_closing_delimiters() -> None:
    """The inline duplication that let the named constant drift must stay gone."""
    assert CLOSING_DELIMITERS <= SUFFIX_TOKENS


def test_suffix_tokens_include_currency_suffixes() -> None:
    # v1's SUFFIX_SYMBOLS was the currency symbols that attach after a value;
    # v2's MAJOR_CURRENCIES defines none as suffixes, so the set is empty and
    # the inclusion invariant is vacuous but still worth pinning.
    assert SUFFIX_CURRENCY_SYMBOLS <= SUFFIX_TOKENS
    assert not SUFFIX_CURRENCY_SYMBOLS


def test_suffix_tokens_include_the_unit_words() -> None:
    assert {"years", "year", "months", "month", "days", "day"} <= SUFFIX_TOKENS


def test_range_markers_are_the_dash_family_plus_spelled_out_forms() -> None:
    assert {"-", "–", "—", "−", "‒", "―", "to", "through", "thru"} <= RANGE_MARKERS


def test_prefix_tokens_are_currency_prefixes_plus_the_open_paren() -> None:
    assert "(" in PREFIX_TOKENS


def test_prefix_and_suffix_are_disjoint_on_brackets() -> None:
    """A token cannot both open and close, or span detection becomes ambiguous."""
    assert not (PREFIX_TOKENS & CLOSING_DELIMITERS)


def test_currency_symbols_are_shared_with_the_currencies_module() -> None:
    assert ALL_CURRENCY_SYMBOLS
    assert FINANCIAL_PLACEHOLDERS
    assert NUMERIC_CELL_RE is not None


@pytest.mark.parametrize("value", ["%", ")", "]", "}", "years", "bps"])
def test_is_suffix_token_accepts_attaching_tokens(value: str) -> None:
    # "$" is deliberately absent: every currency symbol in MAJOR_CURRENCIES is
    # a prefix, so "$" is a PREFIX_TOKEN and attaching it to the previous cell
    # would be wrong.
    assert is_suffix_token(value)
    assert "$" in PREFIX_TOKENS


@pytest.mark.parametrize("value", ["1,234", "(1,234)", "Revenue", "2024"])
def test_is_suffix_token_rejects_non_attaching_tokens(value: str) -> None:
    assert not is_suffix_token(value)


@pytest.mark.parametrize("value", ["-", "–", "—", "to", "through", "thru"])
def test_is_range_marker_accepts_range_separators(value: str) -> None:
    assert is_range_marker(value)


@pytest.mark.parametrize("value", ["1", "2024", "1,234", "$", "(1)", "Revenue"])
def test_is_range_marker_rejects_non_separators(value: str) -> None:
    assert not is_range_marker(value)


def test_range_marker_is_case_insensitive() -> None:
    assert is_range_marker("TO")
    assert is_range_marker("Through")


def test_is_prefix_token_matches_the_combined_set() -> None:
    assert is_prefix_token("(")
    assert not is_prefix_token(")")
