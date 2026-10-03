"""Equity and structured derivative instruments (ASC 815)."""

from __future__ import annotations

from edgar_sec.domain.taxonomy.schedules.derivatives.engine import (
    build_derivative_grammar,
)
from edgar_sec.foundation.text.compounds import (
    expand_alternations,
    expand_variants,
)

EQUITY_INDICES: tuple[str, ...] = (
    "s&p 500",
    "sp 500",
    "nasdaq 100",
    "nasdaq composite",
    "russell 2000",
    "russell 1000",
    "dow jones",
    "msci world",
    "msci emerging markets",
    "msci eafe",
    "ftse 100",
    "nikkei 225",
    "euro stoxx 50",
    "equity index",
)

EQUITY_UNDERLYINGS: tuple[str, ...] = (
    *EQUITY_INDICES,
    "equity",
    "forward share purchase",
    "accelerated share repurchase",
)

EQ_DERIVATIVE_BASES: tuple[str, ...] = (
    "swap",
    "option",
    "call option",
    "put option",
    "futures",
    "collar",
    "derivative",
)

EQUITY_INDEX_DERIVATIVES: tuple[str, ...] = build_derivative_grammar(
    underlyings=EQUITY_UNDERLYINGS,
    bases=EQ_DERIVATIVE_BASES,
)

EMBEDDED_STRUCTURED_DERIVATIVES: tuple[str, ...] = expand_alternations(
    expand_variants(
        (
            "embedded conversion option",
            "embedded conversion feature",
            "bifurcated conversion option",
            "conversion option liability",
            "capped call",
            "capped call option",
            "derivative-classified warrant",
            "liability-classified warrant",
            "warrant liability",
            "fair value of warrant liabilities",
            "fair value of derivative warrant liabilities",
        )
    ),
)

EQUITY_DERIVATIVE_TERMS: tuple[str, ...] = expand_alternations(
    EQUITY_INDEX_DERIVATIVES,
    EMBEDDED_STRUCTURED_DERIVATIVES,
)

EQUITY_EMPLOYEE_COMP_GUARDS: tuple[str, ...] = expand_variants(
    (
        "stock options granted",
        "restricted stock units",
        "weighted-average exercise price",
        "service period",
        "options granted",
        "grant date fair value",
        "stock appreciation rights",
        "stock splits",
        "stock dividends",
    )
)

EQUITY_UNIGRAM_VETOES: tuple[str, ...] = (
    "rsus",
    "psus",
    "dsus",
    "espp",
)
