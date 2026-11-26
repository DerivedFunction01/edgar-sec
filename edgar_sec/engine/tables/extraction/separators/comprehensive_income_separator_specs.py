"""Comprehensive-income separator specs
(TEST_COMPREHENSIVE_INCOME_SEPARATOR). Registry data for the
routed cascade: cascade A with the rows leg narrowed past
21 rows, priced on the corefin-compincome populations.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ComprehensiveIncomeSeparatorSpec:
    """One family's routed separator: the cascade as data.

    The determined core is the statement walk, read over
    the candidate's stub keys.
    """

    family: str
    max_rows: int
    span_years_min: int
    walk_begin_terms: tuple[str, ...]
    walk_end_terms: tuple[str, ...]
    oci_terms: tuple[str, ...]
    components_total_terms: tuple[str, ...]
    descent_terms: tuple[str, ...]
    equity_host_terms: tuple[str, ...]
    equity_host_min: int
    tax_header_phrases: tuple[str, ...]


COMPREHENSIVE_INCOME_SEPARATOR_SPECS: dict[str, ComprehensiveIncomeSeparatorSpec] = {
    "comprehensive_income": ComprehensiveIncomeSeparatorSpec(
        family="comprehensive_income",
        max_rows=21,
        span_years_min=4,
        walk_begin_terms=("net income", "net loss", "net earnings"),
        walk_end_terms=(
            "comprehensive income",
            "comprehensive loss",
            "total comprehensive",
        ),
        oci_terms=(
            "other comprehensive",
            "foreign currency translation",
            "translation adjustment",
            "unrealized",
            "available for sale",
            "pension",
            "postretirement",
            "hedging",
            "hedge",
            "derivative",
            "reclassification",
            "securities",
        ),
        components_total_terms=("other comprehensive",),
        descent_terms=(
            "operating income",
            "income from operations",
            "operating loss",
            "loss from operations",
            "gross profit",
            "cost of revenues",
            "cost of goods sold",
            "total operating expenses",
        ),
        equity_host_terms=(
            "common stock",
            "additional paid",
            "retained earnings",
            "treasury stock",
            "paid-in capital",
            "paid in capital",
        ),
        equity_host_min=2,
        tax_header_phrases=("pretax", "pre tax", "before tax"),
    ),
}
