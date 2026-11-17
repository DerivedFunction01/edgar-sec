"""Measure-set spec registry: the Step 3 kind's parameter table.

Each spec is one filed form's priced measure groups, keyed by
test_id; the evaluator lives in measure_set, the cross-kind
form-test entries in form_test_specs."""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.engine.tables.extraction.profiles import PROV_STEP3_PRICING


@dataclass(frozen=True, slots=True)
class MeasureSetSpec:
    """Measure-set parameters for one test, keyed by test_id below.
    Each group is one filed measure's phrasings; a pass needs
    min_groups groups present and no refused term (Step 3 pricing)."""

    groups: tuple[tuple[str, ...], ...]
    min_groups: int
    subject_terms: tuple[str, ...] = ()
    refused_terms: tuple[str, ...] = ()
    provenance: str = PROV_STEP3_PRICING


# Measure-set parameters, keyed by test_id (the per-kind table).
# Phrasings are normalized text, matched over the table's stub,
# header and caption text, orientation-free (Step 3 pricing).
MEASURE_SET_SPECS_BY_TEST_ID: dict[str, MeasureSetSpec] = {
    "shares_purchased_measure_set": MeasureSetSpec(
        groups=(
            ("average price paid per share", "average price paid"),
            ("may yet be purchased",),
            ("publicly announced plans or programs", "publicly announced"),
            ("total number of shares purchased", "total shares purchased"),
        ),
        min_groups=2,
    ),
    "valuation_model_assumptions_measure_set": MeasureSetSpec(
        groups=(
            ("expected volatility", "volatility"),
            ("expected dividend yield", "dividend yield", "expected dividends"),
            ("expected term", "expected life", "expected option life"),
            (
                "risk free interest rate",
                "risk free rate",
                "risk free interest",
                "interest rate",
            ),
            ("underlying asset price", "underlying stock price", "stock price"),
            ("exercise price", "strike price"),
            ("discount rate",),
        ),
        min_groups=3,
        refused_terms=("level 3", "unobservable"),
    ),
    "warrant_activity_rollforward": MeasureSetSpec(
        groups=(
            (
                "outstanding at beginning of period",
                "outstanding at beginning of year",
                "balance at beginning of period",
                "beginning balance",
            ),
            ("granted", "issued"),
            ("exercised",),
            ("expired", "forfeited", "cancelled", "canceled"),
            (
                "outstanding at end of period",
                "outstanding at end of year",
                "balance at end of period",
                "ending balance",
            ),
            ("weighted average exercise price", "exercise price"),
        ),
        min_groups=4,
        subject_terms=("warrant",),
    ),
    "warrant_outstanding_listing": MeasureSetSpec(
        groups=(
            ("exercise price", "exercise prices"),
            (
                "remaining contractual life",
                "remaining contractual term",
                "remaining life",
            ),
            (
                "warrants outstanding",
                "number outstanding",
                "shares issuable",
                "shares of common stock issuable",
            ),
            ("exercisable",),
        ),
        min_groups=2,
        subject_terms=("warrant",),
    ),
    "combined_operations_ci_measure_set": MeasureSetSpec(
        groups=(
            (
                "revenue",
                "gross profit",
                "operating income",
                "income from operations",
                "operating expenses",
                "cost of revenues",
                "cost of revenue",
            ),
            (
                "other comprehensive income",
                "other comprehensive loss",
                "foreign currency translation",
                "unrealized gain",
                "unrealized loss",
                "net unrealized",
            ),
            ("comprehensive income", "comprehensive loss", "total comprehensive"),
        ),
        min_groups=3,
    ),
}
