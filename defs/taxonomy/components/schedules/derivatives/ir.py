"""Interest rate derivative instruments and hedging taxonomy (ASC 815)."""

from __future__ import annotations

from defs.taxonomy.components.schedules.derivatives.engine import (
    build_derivative_grammar,
    build_pay_receive_swaps,
)
from defs.text.compounds import (
    expand_alternations,
    expand_variants,
)

# Benchmark interest rates (singular canonical)
BENCHMARK_RATES: tuple[str, ...] = (
    "sofr",
    "libor",
    "euribor",
    "sonia",
    "estr",
    "eonia",
    "eurodollar",
)

# Interest rate underlying prefixes
IR_UNDERLYINGS: tuple[str, ...] = (
    "interest rate",
    "treasury rate",
    "treasury",
    "benchmark rate",
    "floating rate",
    "fixed rate",
    *BENCHMARK_RATES,
)

# Canonical singular IR instrument bases (including IR-specific cap, floor, lock)
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

# Dedicated IR structures & forward agreements
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
