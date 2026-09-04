"""Credit default derivative instruments (ASC 815)."""

from __future__ import annotations

from defs.taxonomy.components.schedules.derivatives.engine import (
    build_derivative_grammar,
)

CREDIT_UNDERLYINGS: tuple[str, ...] = (
    "credit default",
    "cds",
    "single-name cds",
    "index cds",
    "cdx",
    "itraxx",
    "credit derivative",
)

CREDIT_BASES: tuple[str, ...] = (
    "swap",
    "swaption",
    "derivative",
    "protection purchased",
    "protection sold",
)

CREDIT_DERIVATIVE_TERMS: tuple[str, ...] = build_derivative_grammar(
    underlyings=CREDIT_UNDERLYINGS,
    bases=CREDIT_BASES,
)
