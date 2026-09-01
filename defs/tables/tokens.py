"""Authoritative token vocabulary and derived predicates for table processing."""

from __future__ import annotations

import re

from defs.regex import build_alternation

from .currencies import MAJOR_CURRENCIES
from .units import MEASUREMENT_UNITS

SUFFIX_TOKENS = frozenset({"%", "pt", "bps", ")", "%)"})
PREFIX_TOKENS = frozenset({"(", "-"})
BULLET_MARKERS = frozenset({"o", "*", "-", "+", "•", "·", "\x95", "–", "—", "&#149;"})

PREFIX_SYMBOLS = frozenset(
    symbol
    for data in MAJOR_CURRENCIES.values()
    if data.get("prefix")
    for symbol in data.get("symbols", [])
)
SUFFIX_SYMBOLS = frozenset(
    symbol
    for data in MAJOR_CURRENCIES.values()
    if data.get("suffix")
    for symbol in data.get("symbols", [])
)
ALL_CURRENCY_SYMBOLS = PREFIX_SYMBOLS | SUFFIX_SYMBOLS
UNIT_SYMBOLS: set[str] = set()
for _unit_data in MEASUREMENT_UNITS.values():
    UNIT_SYMBOLS.update(_unit_data.get("symbols", []))

_EMPTY_NUMERIC_MARKERS = frozenset({"—", "-", "–"})
FINANCIAL_PLACEHOLDERS = frozenset(
    {
        *(_EMPTY_NUMERIC_MARKERS | {"*"}),
        *(
            f"{symbol}{marker}"
            for symbol in ALL_CURRENCY_SYMBOLS
            for marker in _EMPTY_NUMERIC_MARKERS
        ),
        *(
            f"{marker}{suffix}"
            for marker in _EMPTY_NUMERIC_MARKERS
            for suffix in ("*", ")", "%")
        ),
        "na",
        "n/a",
        "none",
        "nil",
    }
)
_FINANCIAL_PLACEHOLDERS_CASEFOLD = frozenset(
    placeholder.casefold() for placeholder in FINANCIAL_PLACEHOLDERS
)

_CURRENCY_ALTERNATION = build_alternation(
    sorted(ALL_CURRENCY_SYMBOLS), auto_escape=True, sort_longest_first=True
)
_UNIT_ALTERNATION = build_alternation(
    sorted(UNIT_SYMBOLS), auto_escape=True, sort_longest_first=True
)
CURRENCY_TOKEN_RE = re.compile(rf"(?:{_CURRENCY_ALTERNATION})")
UNIT_TOKEN_RE = re.compile(rf"(?:{_UNIT_ALTERNATION})\b", re.IGNORECASE)
NUMERIC_CELL_RE = re.compile(
    rf"^(?:{_CURRENCY_ALTERNATION}\s*)?\(?\s*"
    rf"(?:{_CURRENCY_ALTERNATION}\s*)?[\d,\.]+"
    rf"(?:\s*(?:{_UNIT_ALTERNATION}|%))?"
    rf"(?:\s*-\s*(?:{_CURRENCY_ALTERNATION}\s*)?[\d,\.]+"
    rf"(?:\s*(?:{_UNIT_ALTERNATION}|%))?)?"
    rf"\s*(?:{_CURRENCY_ALTERNATION})?\s*\)?\s*%?$"
)
_NUMERIC_STRIP_RE = re.compile(
    rf"(?:{_CURRENCY_ALTERNATION}|{_UNIT_ALTERNATION}|[%()\-,])"
)


def is_financial_placeholder(value: str) -> bool:
    """Return whether a cell is an exact configured financial placeholder."""
    return value.strip().casefold() in _FINANCIAL_PLACEHOLDERS_CASEFOLD


def is_prefix_token(value: str) -> bool:
    """Return whether a cell is a token that attaches to the next cell."""
    return value.strip() in PREFIX_SYMBOLS or value.strip() in PREFIX_TOKENS


def is_suffix_token(value: str) -> bool:
    """Return whether a cell is a token that attaches to the previous cell."""
    return value.strip() in SUFFIX_SYMBOLS or value.strip().casefold() in SUFFIX_TOKENS


def is_numeric_cell(value: str) -> bool:
    """Recognize numeric cells using registered currencies and placeholders."""
    value = value.strip()
    return bool(NUMERIC_CELL_RE.fullmatch(value) or is_financial_placeholder(value))


def is_numeric_start(value: str) -> bool:
    """Return whether a cell starts with a numeric value after token removal."""
    clean = CURRENCY_TOKEN_RE.sub("", value)
    clean = _NUMERIC_STRIP_RE.sub("", clean).replace(" ", "")
    return bool(clean) and (clean[0].isdigit() or clean.startswith(("-", ".")))


__all__ = [
    "ALL_CURRENCY_SYMBOLS",
    "BULLET_MARKERS",
    "CURRENCY_TOKEN_RE",
    "FINANCIAL_PLACEHOLDERS",
    "NUMERIC_CELL_RE",
    "PREFIX_SYMBOLS",
    "PREFIX_TOKENS",
    "SUFFIX_SYMBOLS",
    "SUFFIX_TOKENS",
    "is_financial_placeholder",
    "is_numeric_cell",
    "is_numeric_start",
    "is_prefix_token",
    "is_suffix_token",
]
