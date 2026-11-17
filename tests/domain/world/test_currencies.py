"""Tests for the domain.world currency substrate."""

from __future__ import annotations

import re

import pytest

from edgar_sec.domain.world.currencies import (
    ALL_CURRENCY_SYMBOLS,
    CURRENCIES,
    PREFIX_SYMBOLS,
    SINGLE_CHARACTER_SYMBOL_CLASS,
    SINGLE_CHARACTER_SYMBOLS,
    SUFFIX_SYMBOLS,
    currencies_for_name,
    currencies_for_symbol,
    currency,
)


def test_code_set_is_the_attested_eighteen() -> None:
    assert set(CURRENCIES) == {
        "USD",
        "EUR",
        "GBP",
        "JPY",
        "CAD",
        "AUD",
        "CHF",
        "INR",
        "CNY",
        "HKD",
        "TWD",
        "KRW",
        "SGD",
        "BRL",
        "MXN",
        "SEK",
        "ILS",
        "DKK",
    }


def test_symbol_partition_matches_the_tables_standing() -> None:
    # The standing the production numeric grammar was wired to:
    # every adopted currency prefix, the suffix set empty, and the
    # DKK record adds no new symbol ("kr" already stands via SEK).
    assert SUFFIX_SYMBOLS == frozenset()
    assert PREFIX_SYMBOLS == ALL_CURRENCY_SYMBOLS
    assert len(ALL_CURRENCY_SYMBOLS) == 30
    assert "$" in PREFIX_SYMBOLS
    assert "€" in PREFIX_SYMBOLS
    assert "kr" in PREFIX_SYMBOLS


def test_records_carry_names_demonyms_and_country_links() -> None:
    usd = currency("USD")
    assert usd.demonym == "american"
    assert usd.country == "US"
    assert "dollar" in usd.names
    sek = currency("SEK")
    assert sek.demonym == "swedish"
    assert "krona" in sek.names
    dkk = currency("DKK")
    assert dkk.demonym == "danish"
    assert dkk.country == "DK"
    assert currency("EUR").country is None


def test_kr_symbol_ambiguity_is_carried_as_data() -> None:
    assert currencies_for_symbol("kr") == ("SEK", "DKK")
    assert currencies_for_symbol("$") == ("USD",)


def test_ambiguous_names_are_declared() -> None:
    assert "pound" in currency("GBP").ambiguous_names
    assert "yen" in currency("JPY").ambiguous_names
    assert "won" in currency("KRW").ambiguous_names
    assert currencies_for_name("krone") == ("DKK",)


def test_single_character_class_is_homed_here() -> None:
    assert SINGLE_CHARACTER_SYMBOLS == {"$", "€", "£", "¥", "₹", "₩", "₪"}
    # The class body escapes each symbol (re.escape), so its
    # members are read back escape-aware, as in the consumer pin.
    members = set(re.findall(r"\\?(.)", SINGLE_CHARACTER_SYMBOL_CLASS))
    assert members == set(SINGLE_CHARACTER_SYMBOLS)
    assert "kr" not in SINGLE_CHARACTER_SYMBOL_CLASS


def test_unknown_code_raises() -> None:
    with pytest.raises(KeyError):
        currency("NOK")
