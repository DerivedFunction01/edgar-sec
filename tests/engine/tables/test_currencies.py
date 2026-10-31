"""Currency symbol inventory used to build the numeric-cell grammar."""

from __future__ import annotations

from edgar_sec.engine.tables.currencies import (
    ALL_CURRENCY_SYMBOLS,
    MAJOR_CURRENCIES,
    PREFIX_SYMBOLS,
    SUFFIX_SYMBOLS,
)
from edgar_sec.engine.tables.units import MEASUREMENT_UNITS, UNIT_SYMBOLS


def test_every_major_currency_declares_at_least_one_symbol() -> None:
    assert MAJOR_CURRENCIES
    for code, data in MAJOR_CURRENCIES.items():
        assert data["symbols"], code
        assert data["prefix"] or data["suffix"], code


def test_prefix_and_suffix_sets_are_disjoint() -> None:
    assert not (PREFIX_SYMBOLS & SUFFIX_SYMBOLS)
    assert ALL_CURRENCY_SYMBOLS == PREFIX_SYMBOLS | SUFFIX_SYMBOLS


def test_measurement_units_feed_the_unit_symbol_vocabulary() -> None:
    assert MEASUREMENT_UNITS
    assert "mg" in UNIT_SYMBOLS
    assert "MMBtu" in UNIT_SYMBOLS
    assert "not-a-unit" not in UNIT_SYMBOLS
