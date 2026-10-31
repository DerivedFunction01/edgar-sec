"""Interest rate derivative instruments and hedging taxonomy (ASC 815)."""

from __future__ import annotations

from edgar_sec.domain.taxonomy.schedules.derivatives.engine import (
    build_derivative_grammar,
    build_pay_receive_swaps,
)
from edgar_sec.foundation.text.compounds import (
    expand_alternations,
    expand_variants,
)

BENCHMARK_RATES: tuple[str, ...] = (
    "sofr",
    "libor",
    "euribor",
    "sonia",
    "estr",
    "eonia",
    "eurodollar",
)

IR_UNDERLYINGS: tuple[str, ...] = (
    "interest rate",
    "treasury rate",
    "treasury",
    "benchmark rate",
    "floating rate",
    "fixed rate",
    *BENCHMARK_RATES,
)

IR_BASES: tuple[str, ...] = (
    "swap",
    "swaption",
    "cap",
    "floor",
    "collar",
    "lock",
    "basis swap",
    "spread",
    "derivative",
)

IR_STRUCTURES: tuple[str, ...] = expand_variants(
    (
        "forward rate agreement",
        "forward starting swap",
    )
)

IR_DERIVATIVE_TERMS: tuple[str, ...] = expand_alternations(
    build_pay_receive_swaps(),
    build_derivative_grammar(
        underlyings=IR_UNDERLYINGS,
        bases=IR_BASES,
    ),
    IR_STRUCTURES,
)
