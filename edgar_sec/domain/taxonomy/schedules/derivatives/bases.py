"""Canonical singular derivative instrument bases, qualifiers, and contract suffixes."""

from __future__ import annotations

# Core 1-word unambiguous bases
CORE_UNAMBIGUOUS_BASES: tuple[str, ...] = (
    "swap",
    "swaption",
    "collar",
    "futures",
    "straddle",
)

# Unambiguous 2-word multi-asset compound bases
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

# True Universal Context-Bound Bases (polysemous bare unigrams requiring underlying or suffix)
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


# Unambiguous derivative & hedging suffixes (inherently financial derivative terms)
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

# Ambiguous contract suffixes (generic legal terms; safe only when modifying a derivative base)
AMBIGUOUS_CONTRACT_SUFFIXES: tuple[str, ...] = (
    "contract",
    "agreement",
    "arrangement",
    "instrument",
    "position",
)

# Balance sheet / financial statement qualifiers
BALANCE_SHEET_QUALIFIERS: tuple[str, ...] = (
    "asset",
    "liability",
)

# Canonical combined contract suffixes
CONTRACT_SUFFIXES: tuple[str, ...] = (
    *AMBIGUOUS_CONTRACT_SUFFIXES,
    *UNAMBIGUOUS_DERIVATIVE_SUFFIXES,
)
