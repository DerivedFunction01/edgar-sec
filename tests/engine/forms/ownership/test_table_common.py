"""Tests for the shared ownership table alignment primitives."""

from edgar_sec.engine.forms.common.numbers import extract_schema_number


def test_extract_number_fast_path_preserves_numeric_fallbacks() -> None:
    assert extract_schema_number("00123") == "123"
    assert extract_schema_number("1,234.50") == "1234.50"
    assert extract_schema_number("$8.00") == "8.00"
    assert extract_schema_number("123456789012345678.90") == "123456789012345678.90"
    assert extract_schema_number("²") is None
