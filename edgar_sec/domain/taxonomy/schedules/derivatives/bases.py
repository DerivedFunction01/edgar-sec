"""Canonical singular derivative instrument bases, qualifiers, and contract suffixes."""

from __future__ import annotations

CORE_UNAMBIGUOUS_BASES: tuple[str, ...] = (
    "swap",
    "swaption",
    "collar",
    "futures",
    "straddle",
)

COMPOUND_UNAMBIGUOUS_BASES: tuple[str, ...] = (
    "basis swap",
    "total return swap",
    "variance swap",
    "volatility swap",
    "call spread",
    "put spread",
    "call option",
    "put option",
    "costless collar",
    "zero-cost collar",
)

UNIVERSAL_UNAMBIGUOUS_BASES: tuple[str, ...] = (
    *CORE_UNAMBIGUOUS_BASES,
    *COMPOUND_UNAMBIGUOUS_BASES,
)

UNIVERSAL_CONTEXT_BOUND_BASES: tuple[str, ...] = (
    "forward",
    "option",
    "spread",
    "derivative",
)

UNIVERSAL_BASES: tuple[str, ...] = (
    *UNIVERSAL_UNAMBIGUOUS_BASES,
    *UNIVERSAL_CONTEXT_BOUND_BASES,
)


UNAMBIGUOUS_DERIVATIVE_SUFFIXES: tuple[str, ...] = (
    "derivative instrument",
    "derivative contract",
    "derivative asset",
    "derivative liability",
    "derivative position",
    "hedging instrument",
    "hedging contract",
    "hedging arrangement",
    "hedging position",
)

AMBIGUOUS_CONTRACT_SUFFIXES: tuple[str, ...] = (
    "contract",
    "agreement",
    "arrangement",
    "instrument",
    "position",
)

BALANCE_SHEET_QUALIFIERS: tuple[str, ...] = (
    "asset",
    "liability",
)

CONTRACT_SUFFIXES: tuple[str, ...] = (
    *AMBIGUOUS_CONTRACT_SUFFIXES,
    *UNAMBIGUOUS_DERIVATIVE_SUFFIXES,
)
