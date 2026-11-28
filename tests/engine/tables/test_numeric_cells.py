"""Financial numeric-cell grammar: whole-cell matches, placeholders, prefixes."""

from __future__ import annotations

import pytest

from edgar_sec.engine.forms.common.values.numbers import SCHEMA_PERCENT_RE
from edgar_sec.engine.tables.numeric_cells import (
    ALL_CURRENCY_SYMBOLS,
    EPS_VALUE_POLICY,
    FINANCIAL_PLACEHOLDERS,
    INCOME_VALUE_POLICY,
    LEASE_VALUE_POLICY,
    NUMERIC_CELL_RE,
    PREFIX_SYMBOLS,
    ROLLFORWARD_VALUE_POLICY,
    STRICT_NUMERIC_CELL_RE,
    SUFFIX_SYMBOLS,
    TAX_VALUE_POLICY,
    is_financial_placeholder,
    is_numeric_cell,
    is_numeric_start,
    is_strict_numeric_cell,
    parse_cell_value,
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
    # The digit class is `[\d,.]`, so such a value is numeric whatever its punctuation means.
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


@pytest.mark.parametrize(
    "value",
    [
        "123",
        "1,234",
        "1,234.56",
        "-123",
        "$-123",
        "-1,234.56",
        "$1,234.56",
        "(1,234)",
        "($1,234)",
        "(5)",
        "1,2,3",
        ",",
    ],
)
def test_strict_seat_grammar_accepts_the_seats_figures(value: str) -> None:
    assert is_strict_numeric_cell(value) is True


@pytest.mark.parametrize(
    "value",
    [".5", "123.", "1.2.3", "5%", "1,000/2,000", "€100", "$(5)", "N/A", "-", ""],
)
def test_strict_seat_grammar_rejects_the_broad_forms(value: str) -> None:
    assert is_strict_numeric_cell(value) is False


def test_strict_and_broad_grammars_diverge_in_both_directions() -> None:
    assert is_strict_numeric_cell("-123") is True
    assert is_numeric_cell("-123") is False
    assert is_strict_numeric_cell("N/A") is False
    assert is_numeric_cell("N/A") is True


def test_strict_seat_grammar_does_not_strip() -> None:
    assert is_strict_numeric_cell(" 123") is False
    assert is_strict_numeric_cell("123 ") is False


def test_strict_seat_grammar_pattern_is_the_seats_own() -> None:
    assert STRICT_NUMERIC_CELL_RE.pattern == r"^\(?\$?-?[\d,]+(\.\d+)?\)?$"
    assert STRICT_NUMERIC_CELL_RE.match("1,234 widgets") is None


_VALUE_POLICIES = {
    "eps": EPS_VALUE_POLICY,
    "income": INCOME_VALUE_POLICY,
    "rollforward": ROLLFORWARD_VALUE_POLICY,
    "tax": TAX_VALUE_POLICY,
    "lease": LEASE_VALUE_POLICY,
}


@pytest.mark.parametrize(
    "cell,policy_name,expected_value,expected_numeric",
    [
        ("1 234", "eps", 1234.0, True),
        ("1 234", "income", None, False),
        ("1 234", "rollforward", None, False),
        ("1 234", "tax", None, False),
        ("1 234", "lease", None, False),
        ("((5))", "eps", None, False),
        ("((5))", "income", -5.0, True),
        ("((5))", "rollforward", None, False),
        ("((5))", "tax", None, False),
        ("((5))", "lease", None, False),
        ("(123", "eps", None, False),
        ("(123", "income", 123.0, True),
        ("(123", "rollforward", 123.0, True),
        ("(123", "tax", 123.0, True),
        ("(123", "lease", 123.0, True),
        ("%12", "eps", None, False),
        ("%12", "income", 12.0, True),
        ("%12", "rollforward", None, False),
        ("%12", "tax", None, False),
        ("%12", "lease", None, False),
        ("1e5", "eps", 100000.0, True),
        ("1e5", "income", 100000.0, True),
        ("1e5", "rollforward", None, False),
        ("1e5", "tax", None, False),
        ("1e5", "lease", None, False),
        ("", "eps", 0.0, False),
        ("", "income", None, False),
        ("", "rollforward", None, False),
        ("", "tax", None, False),
        ("", "lease", None, False),
        ("(1,234)", "eps", -1234.0, True),
        ("(1,234)", "income", -1234.0, True),
        ("(1,234)", "rollforward", -1234.0, True),
        ("(1,234)", "tax", -1234.0, True),
        ("(1,234)", "lease", -1234.0, True),
        ("5%", "eps", None, False),
        ("5%", "income", 5.0, True),
        ("5%", "rollforward", 5.0, True),
        ("5%", "tax", 5.0, True),
        ("5%", "lease", 5.0, True),
        ("5 percent", "eps", None, False),
        ("5 percent", "income", None, False),
        ("5 percent", "rollforward", None, False),
        ("5 percent", "tax", 5.0, True),
        ("5 percent", "lease", None, False),
        ("-", "eps", 0.0, False),
        ("-", "rollforward", None, False),
        ("-", "tax", None, False),
        ("*", "eps", None, False),
        ("*", "rollforward", None, False),
        ("*", "tax", None, False),
    ],
)
def test_parse_cell_value_reproduces_each_priced_parse(
    cell: str, policy_name: str, expected_value: float | None, expected_numeric: bool
) -> None:
    parsed = parse_cell_value(
        cell, _VALUE_POLICIES[policy_name], schema_re=SCHEMA_PERCENT_RE
    )
    assert parsed.value == expected_value
    assert parsed.is_numeric is expected_numeric


def test_parse_cell_value_token_facts() -> None:
    assert parse_cell_value("", EPS_VALUE_POLICY).is_dash is True
    assert parse_cell_value("-", EPS_VALUE_POLICY).is_dash is True
    star = parse_cell_value("*", EPS_VALUE_POLICY)
    assert star.is_dash is False and star.is_zero_token is True
    assert parse_cell_value("5%", EPS_VALUE_POLICY).is_percent is True
