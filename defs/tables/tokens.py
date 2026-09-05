"""Authoritative token vocabulary and derived predicates for table processing."""

from __future__ import annotations

from defs.text.tokens import BULLET_MARKERS

from .currencies import detect_currency_affix, format_currency
from .numeric_cells import (
    ALL_CURRENCY_SYMBOLS,
    CURRENCY_TOKEN_RE,
    FINANCIAL_PLACEHOLDERS,
    NUMERIC_CELL_RE,
    PREFIX_SYMBOLS,
    SUFFIX_SYMBOLS,
    is_financial_placeholder,
    is_numeric_cell,
    is_numeric_start,
)

CLOSING_DELIMITERS = frozenset({")", "]", "}"})
SUFFIX_TOKENS = frozenset(
    {"%", "pt", "bps", "%)", "years", "year", "months", "month", "days", "day"}
    | CLOSING_DELIMITERS
)
PREFIX_TOKENS = frozenset({"(", "-"})
RANGE_MARKERS = frozenset({"-", "–", "—", "−", "‒", "―", "to", "through", "thru"})


def is_prefix_token(value: str) -> bool:
    """Return whether a cell is a token that attaches to the next cell."""
    return value.strip() in PREFIX_SYMBOLS or value.strip() in PREFIX_TOKENS


def is_suffix_token(value: str) -> bool:
    """Return whether a cell is a token that attaches to the previous cell."""
    return value.strip() in SUFFIX_SYMBOLS or value.strip().casefold() in SUFFIX_TOKENS


def is_range_marker(value: str) -> bool:
    """Return whether a cell is a standalone range separator token."""
    return value.strip().casefold() in RANGE_MARKERS


__all__ = [
    "ALL_CURRENCY_SYMBOLS",
    "BULLET_MARKERS",
    "CLOSING_DELIMITERS",
    "CURRENCY_TOKEN_RE",
    "FINANCIAL_PLACEHOLDERS",
    "NUMERIC_CELL_RE",
    "PREFIX_SYMBOLS",
    "PREFIX_TOKENS",
    "RANGE_MARKERS",
    "SUFFIX_SYMBOLS",
    "SUFFIX_TOKENS",
    "detect_currency_affix",
    "format_currency",
    "is_financial_placeholder",
    "is_numeric_cell",
    "is_numeric_start",
    "is_prefix_token",
    "is_range_marker",
    "is_suffix_token",
]
