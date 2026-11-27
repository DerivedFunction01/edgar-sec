"""Dash character vocabularies shared by text and table recognizers."""

from __future__ import annotations


DASH_CHARS: str = "-\u2010\u2011\u2012\u2013\u2014\u2212"


CELL_DASHES: frozenset[str] = frozenset({"-", "\u2013", "\u2014"})


RANGE_DASHES: frozenset[str] = frozenset(
    {"-", "\u2013", "\u2014", "\u2212", "\u2012", "\u2015"}
)


def is_blank_or_dash(value: str) -> bool:
    """Whether a cell string is empty or a lone cell dash."""
    return value == "" or value in CELL_DASHES


__all__ = [
    "CELL_DASHES",
    "DASH_CHARS",
    "RANGE_DASHES",
    "is_blank_or_dash",
]
