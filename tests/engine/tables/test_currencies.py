"""Unit tests for edgar_sec.engine.tables.currencies."""

from __future__ import annotations

from edgar_sec.engine.tables.currencies import (
    ALL_CURRENCY_SYMBOLS,
    MAJOR_CURRENCIES,
    PREFIX_CURRENCY_SYMBOLS,
    SUFFIX_CURRENCY_SYMBOLS,
)


def test_major_currencies() -> None:
    assert "USD" in MAJOR_CURRENCIES
    assert "EUR" in MAJOR_CURRENCIES
    assert "GBP" in MAJOR_CURRENCIES
    assert "$" in ALL_CURRENCY_SYMBOLS
    assert "€" in ALL_CURRENCY_SYMBOLS
    assert "$" in PREFIX_CURRENCY_SYMBOLS
    assert isinstance(SUFFIX_CURRENCY_SYMBOLS, frozenset)
