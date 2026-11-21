"""Consumer derivations from the substrate stay equal to what they replace."""

from __future__ import annotations

import re

from edgar_sec.domain.world.currencies import (
    ALL_CURRENCY_SYMBOLS,
    SINGLE_CHARACTER_SYMBOL_CLASS,
    SINGLE_CHARACTER_SYMBOLS,
)
from edgar_sec.engine.forms.common import numbers
from edgar_sec.engine.forms.form144.sale_parser import _USD_PREFIX_SPELLINGS
from edgar_sec.engine.tables import numeric_cells


def test_numeric_cells_symbol_sets_are_the_substrates() -> None:
    assert numeric_cells.ALL_CURRENCY_SYMBOLS is ALL_CURRENCY_SYMBOLS
    assert numeric_cells.PREFIX_SYMBOLS
    assert numeric_cells.SUFFIX_SYMBOLS == frozenset()


def test_usd_prefix_spellings_equal_the_retired_literal() -> None:
    assert set(_USD_PREFIX_SPELLINGS) == {"U.S.$", "US $", "US$", "USD"}


def test_scaled_numeric_symbol_class_is_the_single_character_set() -> None:
    expected = {symbol for symbol in ALL_CURRENCY_SYMBOLS if len(symbol) == 1}
    # The retired literal admitted only $, €, £; the substrate's
    # single-character set is the de-duplicated decision.
    assert {"$", "€", "£"} < expected
    assert expected == {"$", "€", "£", "¥", "₹", "₩", "₪"}
    assert SINGLE_CHARACTER_SYMBOLS == expected
    for symbol in expected:
        assert numbers.parse_scaled_number(f"{symbol}1.5 million") is not None


def test_scaled_numeric_still_parses_the_retired_shapes() -> None:
    assert numbers.parse_scaled_number("$1.5 million") is not None
    assert numbers.parse_scaled_number("€2 billion") is not None
    assert numbers.parse_scaled_number("£300 thousand") is not None


def test_numbers_regex_reads_the_homed_class() -> None:
    # The class homes once in domain.world; numbers.py's compiled
    # grammar embeds the substrate's class body verbatim and
    # derives no class of its own.
    pattern = numbers._SCALED_NUMERIC_RE.pattern
    class_body = pattern.split("[", 1)[1].split("]", 1)[0]
    assert class_body == SINGLE_CHARACTER_SYMBOL_CLASS
    assert set(re.findall(r"\\?(.)", class_body)) == set(SINGLE_CHARACTER_SYMBOLS)
