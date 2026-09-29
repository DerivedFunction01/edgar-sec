"""Financial numeric cell vocabulary, predicates, and column start detection."""

from __future__ import annotations

import re

from edgar_sec.engine.tables.currencies import (
    ALL_CURRENCY_SYMBOLS,
    PREFIX_CURRENCY_SYMBOLS,
    SUFFIX_CURRENCY_SYMBOLS,
)
from edgar_sec.foundation.regex.builder import build_alternation

PREFIX_TOKENS = frozenset({"("}) | PREFIX_CURRENCY_SYMBOLS
# Closing brackets are the suffix tokens that attach to the *previous* cell, and
# are also the vocabulary ascii_html tests a rendered boundary against. They are
# named so that SUFFIX_TOKENS is built from them rather than listing them inline.
CLOSING_DELIMITERS = frozenset({")", "]", "}"})
SUFFIX_TOKENS = (
    frozenset(
        {
            "%",
            "pt",
            "bps",
            "%)",
            "years",
            "year",
            "months",
            "month",
            "days",
            "day",
        }
    )
    | CLOSING_DELIMITERS
    | SUFFIX_CURRENCY_SYMBOLS
)
# Standalone range separators between two numeric cells: hyphen, the Unicode
# dashes EDGAR filings use, and the spelled-out forms.
RANGE_MARKERS = frozenset({"-", "–", "—", "−", "‒", "―", "to", "through", "thru"})

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
CURRENCY_TOKEN_RE = re.compile(rf"(?:{_CURRENCY_ALTERNATION})")

NUMERIC_CELL_RE = re.compile(
    rf"^(?:{_CURRENCY_ALTERNATION}\s*)?\(?\s*"
    rf"(?:{_CURRENCY_ALTERNATION}\s*)?[\d,\.]+"
    rf"(?:\s*%)?"
    rf"(?:\s*[-/]\s*(?:{_CURRENCY_ALTERNATION}\s*)?[\d,\.]+"
    rf"(?:\s*%)?)?"
    rf"\s*(?:{_CURRENCY_ALTERNATION})?\s*\)?\s*%?$"
)

_RE_COLUMN_GAP = re.compile(r"[ \t]{2,}")


def is_financial_placeholder(value: str) -> bool:
    """Return whether a cell is an exact configured financial placeholder."""
    return value.strip().casefold() in _FINANCIAL_PLACEHOLDERS_CASEFOLD


def is_numeric_cell(value: str) -> bool:
    """Recognize a numeric cell using registered currencies and placeholders."""
    v = value.strip()
    return bool(NUMERIC_CELL_RE.fullmatch(v) or is_financial_placeholder(v))


def is_prefix_token(value: str) -> bool:
    return value.strip() in PREFIX_TOKENS


def is_suffix_token(value: str) -> bool:
    """Return whether a cell is a token that attaches to the previous cell."""
    return value.strip().casefold() in SUFFIX_TOKENS


def is_range_marker(value: str) -> bool:
    """Return whether a cell is a standalone range separator token."""
    return value.strip().casefold() in RANGE_MARKERS


def numeric_cell_starts(line: str) -> tuple[int, ...]:
    """Positions where a numeric/currency cell begins right after a column gap."""
    stripped_end = len(line.rstrip())
    content_start = len(line) - len(line.lstrip())
    starts: list[int] = []
    for match in _RE_COLUMN_GAP.finditer(line[:stripped_end]):
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
    "CLOSING_DELIMITERS",
    "FINANCIAL_PLACEHOLDERS",
    "NUMERIC_CELL_RE",
    "PREFIX_TOKENS",
    "RANGE_MARKERS",
    "SUFFIX_TOKENS",
    "is_financial_placeholder",
    "is_numeric_cell",
    "is_prefix_token",
    "is_range_marker",
    "is_suffix_token",
    "numeric_cell_starts",
]
