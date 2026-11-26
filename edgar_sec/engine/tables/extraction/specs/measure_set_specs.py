"""Measure-set spec registry: the Step 3 kind's parameter table.

Each spec is one filed form's priced measure groups, keyed by
test_id; the evaluator lives in measure_set, the cross-kind
form-test entries in form_test_specs."""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.engine.tables.extraction.core.subjects.profile_constants import (
    PROV_CI_STEP6_PRICING,
    PROV_S4_GOODWILL_BASE,
    PROV_STEP3_PRICING,
)


@dataclass(frozen=True, slots=True)
class MeasureSetSpec:
    """Measure-set parameters for one test, keyed by test_id below.
    A pass needs min_groups groups present, every required group
    present, and no refused term (Step 3; required groups CI Step 6)."""

    groups: tuple[tuple[str, ...], ...]
    min_groups: int
    subject_terms: tuple[str, ...] = ()
    refused_terms: tuple[str, ...] = ()
    provenance: str = PROV_STEP3_PRICING
    required_groups: tuple[int, ...] = ()
    date_bookend_groups: tuple[int, ...] = ()
    dated_bookend_qualified: bool = False
    subject_position_bound: bool = False
    subject_prose_tail_chars: int = 0


# Measure-set parameters, keyed by test_id (the per-kind table).
# Phrasings are normalized text, matched over the table's stub,
# header and caption text, orientation-free (Step 3 pricing).
MEASURE_SET_SPECS_BY_TEST_ID: dict[str, MeasureSetSpec] = {
    # Item 703 columns in core order (CI Step 6 re-derivation,
    # population-priced): (a) and (b) are the rank-1 purchase pair
    # and are required; a pass needs the pair plus one of (c)/(d).
    # The gold-miss revision adds the filed variant phrasings to
    # all four groups and drops the minimum to the pair alone, so
    # a pair-only activity summary passes on the pair.
    "shares_purchased_measure_set": MeasureSetSpec(
        groups=(
            (
                "total number of shares purchased",
                "total # shares purchased",
                "total shares purchased",
                "number of shares purchased",
                "total number of shares",
                "common shares repurchased",
                "shares repurchased",
                "number of shares repurchased",
            ),
            (
                "average price paid per share",
                "average price paid",
                "average price per share",
                "average price per common share",
                "average per share",
                "per share price",
            ),
            (
                "publicly announced plans or programs",
                "publicly announced",
                "repurchased under the program",
                "purchased under the program",
            ),
            (
                "may yet be purchased",
                "still available under",
                "still available for purchase",
                "remaining under",
                "amount remaining",
            ),
        ),
        min_groups=2,
        provenance=PROV_CI_STEP6_PRICING,
        required_groups=(0, 1),
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
    # ASC 220 single continuous statement, typed groups in rank
    # order (CI Step 6 re-derivation, population-priced): descent,
    # terminus, OCI element, comprehensive total. The core groups
    # (descent, terminus, comprehensive total) are required and
    # the OCI group is supporting — a zero-OCI period presents
    # comprehensive income equal to net income with no OCI lines,
    # and the supporting group must not veto the core (fv4
    # residual pricing, combined-operations-ci register). A
    # standalone CI statement (no descent) still cannot fire.
    # The joint-total form is the test below.
    "combined_operations_ci_measure_set": MeasureSetSpec(
        groups=(
            (
                "operating income",
                "income from operations",
                "operating expenses",
                "operating loss",
                "loss from operations",
                "gross profit",
                "gross margin",
                "cost of revenues",
                "cost of revenue",
                "cost of goods sold",
                "total operating expenses",
                "total revenues",
                "total income",
                "total expenses",
            ),
            ("net income", "net loss", "net earnings", "net (loss) income"),
            (
                "other comprehensive income",
                "other comprehensive loss",
                "foreign currency translation",
                "unrealized gain",
                "unrealized loss",
                "net unrealized",
                "available for sale",
                "translation adjustment",
            ),
            ("comprehensive income", "comprehensive loss", "total comprehensive"),
        ),
        min_groups=3,
        required_groups=(0, 1, 3),
        provenance=PROV_CI_STEP6_PRICING,
    ),
    "combined_operations_ci_joint_measure_set": MeasureSetSpec(
        groups=(
            (
                "operating income",
                "income from operations",
                "operating expenses",
                "operating loss",
                "loss from operations",
                "gross profit",
                "gross margin",
                "cost of revenues",
                "cost of revenue",
                "cost of goods sold",
                "total operating expenses",
            ),
            (
                "net income and comprehensive",
                "net loss and comprehensive",
                "income and comprehensive income",
                "loss and comprehensive loss",
                "net (loss) income and comprehensive",
                "income and comprehensive (loss) income",
            ),
        ),
        min_groups=2,
        provenance=PROV_CI_STEP6_PRICING,
    ),
    # ASC 350-20-50-1 rollforward (S4 adjudication base, recall
    # pricing at size): the ending bookend is the required
    # anchor and may be carried by a dated stub; a pass needs
    # it plus two further groups, with goodwill in walk
    # position.
    "goodwill_rollforward_measure_set": MeasureSetSpec(
        groups=(
            (
                "beginning balance",
                "beginning of period",
                "beginning of year",
                "brought forward",
                "balance at the beginning",
                "at the beginning of the year",
                "at the beginning of the period",
            ),
            (
                "ending balance",
                "end of period",
                "end of year",
                "carried forward",
                "balance at the end",
                "at the end of the year",
                "at the end of the period",
            ),
            ("acquisition", "acquired"),
            ("impairment",),
            (
                "disposition",
                "disposal",
                "derecognized",
                "divestiture",
                "deduction",
                "held for sale",
                "sale of",
            ),
            (
                "adjustment",
                "activity",
                "realignment",
                "translation",
                "foreign currency",
                "deferred tax",
                "measurement period",
                "reclassification",
                "additions",
            ),
        ),
        min_groups=3,
        subject_terms=("goodwill",),
        provenance=PROV_S4_GOODWILL_BASE,
        required_groups=(1,),
        date_bookend_groups=(0, 1),
        dated_bookend_qualified=True,
        subject_position_bound=True,
        subject_prose_tail_chars=400,
    ),
}
