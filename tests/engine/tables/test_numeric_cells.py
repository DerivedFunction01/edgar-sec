"""Financial numeric-cell grammar: whole-cell matches, placeholders, prefixes."""

from __future__ import annotations

import pytest

from edgar_sec.engine.tables.numeric_cells import (
    ALL_CURRENCY_SYMBOLS,
    FINANCIAL_PLACEHOLDERS,
    NUMERIC_CELL_RE,
    PREFIX_SYMBOLS,
    SUFFIX_SYMBOLS,
    is_financial_placeholder,
    is_numeric_cell,
    is_numeric_start,
)


@pytest.mark.parametrize(
    "value",
    [
        "1,234",
        "1,234.00",
        "$ 1,234",
        "$1,234.50",
        "(1,234)",
        "(127,110)",
        "1,000/2,000",
    ],
)
def test_currency_and_range_forms_are_numeric(value: str) -> None:
    assert is_numeric_cell(value) is True


@pytest.mark.parametrize(
    "value",
    ["Revenue", "1,234 widgets", "ITEM 5. MARKET", "2024 and 2025"],
)
def test_prose_is_not_numeric(value: str) -> None:
    assert is_numeric_cell(value) is False


def test_the_digit_group_accepts_any_mix_of_digits_commas_and_periods() -> None:
    # The grammar's digit group is the character class `[\d,.]`, so a value made
    # only of those characters is a numeric cell whatever its punctuation means.
    assert is_numeric_cell("1.2.3") is True
    assert is_numeric_cell("1,,2") is True


@pytest.mark.parametrize("value", ["—", "-", "–", "N/A", "none", "$—", "$-", "-)"])
def test_placeholders_are_numeric_data(value: str) -> None:
    assert is_financial_placeholder(value) is True
    assert is_numeric_cell(value) is True


def test_four_digit_year_is_a_placeholder_free_value() -> None:
    assert is_numeric_cell("2024") is True
    assert is_financial_placeholder("2024") is False


def test_placeholder_membership_is_case_insensitive() -> None:
    assert is_financial_placeholder("N/A") is is_financial_placeholder("n/a")


def test_symbol_partition_comes_from_the_currency_table() -> None:
    assert "$" in PREFIX_SYMBOLS
    assert SUFFIX_SYMBOLS == frozenset()
    assert PREFIX_SYMBOLS <= ALL_CURRENCY_SYMBOLS
    assert "USD" not in FINANCIAL_PLACEHOLDERS


def test_numeric_start_sees_through_currency_and_unit_tokens() -> None:
    assert is_numeric_start("$1,234") is True
    assert is_numeric_start("(1,234)") is True
    assert is_numeric_start("Revenue $1,234") is False


def test_numeric_cell_re_is_a_whole_cell_grammar() -> None:
    assert NUMERIC_CELL_RE.fullmatch("1,234") is not None
    assert NUMERIC_CELL_RE.fullmatch("1,234 widgets") is None
