"""Authoritative token vocabulary and derived predicates for table processing."""

from __future__ import annotations

import re

from defs.regex import build_alternation

from .currencies import MAJOR_CURRENCIES

FINANCIAL_PLACEHOLDERS = frozenset(
    {
        "—",
        "-",
        "–",
        "*",
        "$—",
        "—*",
        "-*",
        "—)",
        "-)",
        "—%",
        "-%",
        "–%",
        "na",
        "n/a",
        "none",
        "nil",
    }
)
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

_CURRENCY_ALTERNATION = build_alternation(
    sorted(ALL_CURRENCY_SYMBOLS), auto_escape=True, sort_longest_first=True
)
CURRENCY_TOKEN_RE = re.compile(rf"(?:{_CURRENCY_ALTERNATION})")
NUMERIC_CELL_RE = re.compile(
    rf"^(?:{_CURRENCY_ALTERNATION})?\s*\(?\s*[\d,\.]+\s*\)?\s*%?$"
)
_NUMERIC_STRIP_RE = re.compile(rf"(?:{_CURRENCY_ALTERNATION}|[%()\-,])")


def is_financial_placeholder(value: str) -> bool:
    """Return whether a cell is an exact configured financial placeholder."""
    return value.strip().casefold() in FINANCIAL_PLACEHOLDERS


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
