"""Foreign exchange and currency derivative instruments (ASC 815)."""

from __future__ import annotations

from edgar_sec.domain.taxonomy.schedules.derivatives.engine import (
    build_derivative_grammar,
)
from edgar_sec.foundation.text.compounds import (
    expand_alternations,
)

STRONG_FX_PREFIXES: tuple[str, ...] = (
    "foreign exchange",
    "foreign currency",
    "fx",
    "cross-currency",
    "multi-currency",
    "non-deliverable",
    "ndf",
    "net investment",
)

FX_BASES: tuple[str, ...] = (
    "forward",
    "swap",
    "option",
    "call option",
    "put option",
    "collar",
    "futures",
    "hedge",
    "derivative",
)

FX_STRONG_COMPOUNDS: tuple[str, ...] = build_derivative_grammar(
    underlyings=STRONG_FX_PREFIXES,
    bases=FX_BASES,
)

FX_WEAK_COMPOUNDS: tuple[str, ...] = build_derivative_grammar(
    underlyings="currency",
    bases=("swap", "option", "forward", "collar", "futures", "derivative"),
)

FX_DERIVATIVE_TERMS: tuple[str, ...] = expand_alternations(
    FX_STRONG_COMPOUNDS,
    FX_WEAK_COMPOUNDS,
)
