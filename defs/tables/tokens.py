"""Authoritative token vocabulary and derived predicates for table processing."""

from __future__ import annotations

from defs.text.syntax.dates import YEAR_RANGE, is_valid_year, is_year_token
from defs.text.syntax.tokens import BULLET_MARKERS

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
PREFIX_TOKENS = frozenset({"("})
RANGE_MARKERS = frozenset({"-", "–", "—", "−", "‒", "―", "to", "through", "thru"})


def is_prefix_token(value: str) -> bool:
    """Return whether a cell is a token that attaches to the next cell."""
    return value.strip() in PREFIX_SYMBOLS or value.strip() in PREFIX_TOKENS


def is_suffix_token(value: str) -> bool:
    """Return whether a cell is a token that attaches to the previous cell."""
    return value.strip() in SUFFIX_SYMBOLS or value.strip().casefold() in SUFFIX_TOKENS


from defs.text.structure.patterns import RE_COLUMN_GAP


def is_range_marker(value: str) -> bool:
    """Return whether a cell is a standalone range separator token."""
    return value.strip().casefold() in RANGE_MARKERS


def numeric_cell_starts(line: str) -> tuple[int, ...]:
    """Positions where a numeric/currency cell begins right after a column gap."""
    stripped_end = len(line.rstrip())
    content_start = len(line) - len(line.lstrip())
    starts: list[int] = []
    for match in RE_COLUMN_GAP.finditer(line[:stripped_end]):
        if match.start() < content_start:
            continue
        tail = line[match.end() :].strip().split(maxsplit=3)
        if not tail:
            continue
        if is_numeric_cell(tail[0]):
            starts.append(match.end())
        elif len(tail) > 1 and is_prefix_token(tail[0]):
            candidate = f"{tail[0]}{tail[1]}"
            if is_numeric_cell(candidate) or is_numeric_cell(f"{tail[0]} {tail[1]}"):
                starts.append(match.end())
            elif len(tail) > 2 and is_prefix_token(tail[1]):
                candidate3 = f"{tail[0]}{tail[1]}{tail[2]}"
                if is_numeric_cell(candidate3) or is_numeric_cell(
                    f"{tail[0]} {tail[1]} {tail[2]}"
                ):
                    starts.append(match.end())
    if not starts and content_start > 0:
        words = line.strip().split(maxsplit=3)
        if words and is_numeric_cell(words[0]):
            starts.append(content_start)
        elif len(words) > 1 and is_prefix_token(words[0]):
            candidate = f"{words[0]}{words[1]}"
            if is_numeric_cell(candidate) or is_numeric_cell(f"{words[0]} {words[1]}"):
                starts.append(content_start)
    return tuple(starts)


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
    "YEAR_RANGE",
    "detect_currency_affix",
    "format_currency",
    "is_financial_placeholder",
    "is_numeric_cell",
    "is_numeric_start",
    "is_prefix_token",
    "is_range_marker",
    "is_suffix_token",
    "is_valid_year",
    "is_year_token",
    "numeric_cell_starts",
]
