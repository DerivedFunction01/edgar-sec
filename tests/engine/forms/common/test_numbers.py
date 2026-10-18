"""Unit tests for common numbers module."""

import pytest

from edgar_sec.engine.forms.common.numbers import (
    clean_numeric,
    format_scaled_number_string,
    parse_scaled_number,
)


def test_clean_numeric_basic_integers_and_floats() -> None:
    assert clean_numeric("5,000") == 5000
    assert clean_numeric("129,323.50") == 129323.50
    assert clean_numeric("0") == 0


def test_clean_numeric_currencies_and_prefixes() -> None:
    assert clean_numeric("$276,487.25") == 276487.25
    assert clean_numeric("€10,000") == 10000
    assert clean_numeric("£8,500.25") == 8500.25
    assert clean_numeric("¥50,000") == 50000
    assert clean_numeric("C$12,000") == 12000
    assert clean_numeric("Up to 6,025") == 6025
    assert clean_numeric("approx. $1,500") == 1500


def test_clean_numeric_negatives_and_nulls() -> None:
    assert clean_numeric("(1,000)") == -1000
    assert clean_numeric("-") is None
    assert clean_numeric("None") is None
    assert clean_numeric("N/A") is None
    assert clean_numeric("") is None
    assert clean_numeric(None) is None


def test_parse_scaled_number_basic() -> None:
    assert parse_scaled_number("25,000") == 25000
    assert parse_scaled_number("$612,007.46") == 612007.46
    assert parse_scaled_number("8,405.104") == 8405.104


def test_parse_scaled_number_magnitudes() -> None:
    assert parse_scaled_number("$250M") == 250000000
    assert parse_scaled_number("133.1M") == 133100000
    assert parse_scaled_number("2.5B") == 2500000000
    assert parse_scaled_number("$1.2 billion") == 1200000000
    assert parse_scaled_number("10.5 thousand") == 10500
    assert parse_scaled_number("150 MM") == 150000000


def test_parse_scaled_number_guardrails() -> None:
    assert parse_scaled_number("10b-5") is None
    assert parse_scaled_number("Rule 10b5-1") is None
    assert parse_scaled_number("Form 10-K") is None
    assert parse_scaled_number("1(b)") is None
    assert parse_scaled_number("3(b)") is None
    assert parse_scaled_number("1b") is None
    assert parse_scaled_number("Suite 10B") is None
    assert parse_scaled_number("Apt 1M") is None
    assert parse_scaled_number("Schedule 13D") is None
    assert parse_scaled_number("001-14649") is None
    assert parse_scaled_number("CUSIP 03783310B") is None


def test_format_scaled_number_string() -> None:
    assert format_scaled_number_string("133.1M") == "133100000"
    assert format_scaled_number_string("$250M") == "250000000"
    assert format_scaled_number_string("$612,007.46") == "612007.46"
    assert format_scaled_number_string("invalid") is None
