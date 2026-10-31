"""ASC 718 Stock-based compensation rollforward terms and tail patterns."""

from __future__ import annotations

import re

from edgar_sec.foundation.regex.builder import build_alternation

STOCK_COMP_PRIMARY_TERMS: tuple[str, ...] = (
    "options outstanding",
    "shares granted",
    "shares exercised",
    "shares forfeited",
    "shares expired",
    "weighted-average exercise price",
    "weighted average exercise price",
    "weighted-average grant date fair value",
    "unrecognized compensation",
    "restricted stock units",
    "option grants",
    "stock awards",
    "unvested shares",
    "outstanding equity awards",
    "named executive officers",
)

STOCK_COMP_SUPPORTING_TERMS: tuple[str, ...] = (
    "stock options",
    "grant date",
    "vesting period",
    "intrinsic value",
    "aggregate intrinsic value",
    "weighted-average remaining contractual term",
)

STOCK_COMP_TAIL_TERMS: tuple[str, ...] = (
    "weighted-average shares outstanding",
    "weighted average shares outstanding",
    "ending balance",
    "beginning balance",
)

_STOCK_COMP_TAIL_PATTERN = build_alternation(
    STOCK_COMP_TAIL_TERMS,
    auto_escape=True,
    flexible_whitespace=True,
    compact=True,
)

STOCK_COMP_TAIL_RE = re.compile(
    rf"^\s*{_STOCK_COMP_TAIL_PATTERN}(?=\s|$)", re.IGNORECASE
)

STOCK_COMP_VETOES: tuple[str, ...] = ("activities",)

__all__ = [
    "STOCK_COMP_PRIMARY_TERMS",
    "STOCK_COMP_SUPPORTING_TERMS",
    "STOCK_COMP_TAIL_RE",
    "STOCK_COMP_TAIL_TERMS",
    "STOCK_COMP_VETOES",
]
