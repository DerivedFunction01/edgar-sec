"""Unit tests for centralized numeric and currency parsing."""

from edgar_sec.engine.forms.common.numbers import clean_numeric


def test_clean_numeric_basic_integers_and_floats():
    """Verify integer and floating point parsing."""
    assert clean_numeric("5,000") == 5000
    assert clean_numeric("129,323.50") == 129323.50
    assert clean_numeric("0") == 0


def test_clean_numeric_currencies_and_prefixes():
    """Verify currency stripping and qualitative prefix handling."""
    assert clean_numeric("$276,487.25") == 276487.25
    assert clean_numeric("€10,000") == 10000
    assert clean_numeric("£8,500.25") == 8500.25
    assert clean_numeric("¥50,000") == 50000
    assert clean_numeric("C$12,000") == 12000
    assert clean_numeric("Up to 6,025") == 6025
    assert clean_numeric("approx. $1,500") == 1500


def test_clean_numeric_negatives_and_nulls():
    """Verify negative parenthesized numbers and null token rejections."""
    assert clean_numeric("(1,000)") == -1000
    assert clean_numeric("-") is None
    assert clean_numeric("None") is None
    assert clean_numeric("N/A") is None
    assert clean_numeric("") is None
    assert clean_numeric(None) is None
