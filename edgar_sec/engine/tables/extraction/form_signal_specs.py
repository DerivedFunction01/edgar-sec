"""Form-signal spec registry: the Step 2 kinds' parameter tables.

Row bounds, signature-absence sets, and placement conjunctions,
each carrying its priced member/false rates over the v3 base.
"""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.engine.tables.extraction.profiles import (
    PROV_STEP2_PRICING,
    TEST_PLACEMENT_CONSISTENCY,
    TEST_ROW_BOUND,
    TEST_SIGNATURE_ABSENCE,
)

# The three kinds' form-test entries (family, kind, test_id,
# points), composed into FORM_TEST_SPECS by form_test_specs
# with the shared Step 2 pricing provenance.
FORM_SIGNAL_TEST_ENTRIES: tuple[tuple[str, str, str, float], ...] = (
    ("balance_sheet", TEST_ROW_BOUND, "balance_sheet_row_bound", 1.0),
    ("cash_flow", TEST_ROW_BOUND, "cash_flow_row_bound", 1.0),
    ("comprehensive_income", TEST_ROW_BOUND, "comprehensive_income_row_bound", 1.0),
    ("equity_statement", TEST_ROW_BOUND, "equity_statement_row_bound", 1.0),
    ("income_statement", TEST_ROW_BOUND, "income_statement_row_bound", 1.0),
    ("inventory", TEST_ROW_BOUND, "inventory_row_bound", 1.0),
    ("ppe", TEST_ROW_BOUND, "ppe_row_bound", 1.0),
    (
        "stock_comp_rollforward",
        TEST_ROW_BOUND,
        "stock_comp_rollforward_row_bound",
        1.0,
    ),
    ("tax_reconciliation", TEST_ROW_BOUND, "tax_reconciliation_row_bound", 1.0),
    ("cash_flow", TEST_SIGNATURE_ABSENCE, "cash_flow_signature_absence", 1.0),
    ("deferred_tax", TEST_SIGNATURE_ABSENCE, "deferred_tax_signature_absence", 1.0),
    ("ppe", TEST_SIGNATURE_ABSENCE, "ppe_signature_absence", 1.0),
    (
        "stock_comp_rollforward",
        TEST_SIGNATURE_ABSENCE,
        "stock_comp_rollforward_signature_absence",
        1.0,
    ),
    (
        "tax_reconciliation",
        TEST_SIGNATURE_ABSENCE,
        "tax_reconciliation_signature_absence",
        1.0,
    ),
    ("balance_sheet", TEST_PLACEMENT_CONSISTENCY, "balance_sheet_placement", 1.0),
    (
        "comprehensive_income",
        TEST_PLACEMENT_CONSISTENCY,
        "comprehensive_income_placement",
        1.0,
    ),
    (
        "eps_reconciliation",
        TEST_PLACEMENT_CONSISTENCY,
        "eps_reconciliation_placement",
        1.0,
    ),
    (
        "income_statement",
        TEST_PLACEMENT_CONSISTENCY,
        "income_statement_placement",
        1.0,
    ),
    (
        "segment_reporting",
        TEST_PLACEMENT_CONSISTENCY,
        "segment_reporting_placement",
        1.0,
    ),
)

ORIENT_FIXED = "fixed"
ORIENT_EITHER_AXIS = "either_axis"


@dataclass(frozen=True, slots=True)
class RowBoundSpec:
    """One family's measured member row envelope (Step 2 pricing).
    Bounds are member grid-row p5..p95 over the v3 base;
    FIXED forms bind as filed, FREE/UNDETERMINED on either axis."""

    family: str
    min_rows: int
    max_rows: int
    orientation: str
    member_pass_rate: float
    false_pass_rate: float
    provenance: str = PROV_STEP2_PRICING


# Row-bound specs, priced per family on the v3 base (Step 2):
# member envelope p5..p95, never one global cut.
ROW_BOUND_SPECS: tuple[RowBoundSpec, ...] = (
    RowBoundSpec("balance_sheet", 21, 54, ORIENT_FIXED, 0.91, 0.247),
    RowBoundSpec("cash_flow", 12, 93, ORIENT_FIXED, 0.97, 0.35),
    RowBoundSpec("comprehensive_income", 6, 21, ORIENT_FIXED, 1.0, 0.818),
    RowBoundSpec("equity_statement", 7, 40, ORIENT_EITHER_AXIS, 1.0, 0.562),
    RowBoundSpec("income_statement", 16, 54, ORIENT_FIXED, 0.91, 0.348),
    RowBoundSpec("inventory", 6, 19, ORIENT_FIXED, 1.0, 0.4),
    RowBoundSpec("ppe", 6, 47, ORIENT_FIXED, 1.0, 0.786),
    RowBoundSpec("stock_comp_rollforward", 6, 19, ORIENT_EITHER_AXIS, 0.96, 0.737),
    RowBoundSpec("tax_reconciliation", 7, 15, ORIENT_EITHER_AXIS, 1.0, 0.727),
)

ROW_BOUND_SPECS_BY_TEST_ID: dict[str, RowBoundSpec] = {
    f"{spec.family}_row_bound": spec for spec in ROW_BOUND_SPECS
}


@dataclass(frozen=True, slots=True)
class SignatureAbsenceSpec:
    """One family's core signature labels (Step 2 pricing).
    Passes when at least one signature label is present;
    total absence is the priced imposter signature."""

    family: str
    signature_labels: tuple[str, ...]
    member_absence_rate: float
    false_absence_rate: float
    provenance: str = PROV_STEP2_PRICING


# Signature-absence specs: signature labels are the family's
# subject-evidence stub terms at member share >= .30, re-priced.
SIGNATURE_ABSENCE_SPECS: tuple[SignatureAbsenceSpec, ...] = (
    SignatureAbsenceSpec(
        "cash_flow",
        (
            "financing activities",
            "operating activities",
            "cash flow",
            "net cash provided",
            "investing activities",
            "cash flows",
            "net cash used",
            "cash flows from financing activities",
            "cash flows from operating activities",
            "cash flows from investing activities",
            "net cash used in investing activities",
            "changes in operating assets and liabilities",
            "net cash provided by operating activities",
            "deferred income tax",
        ),
        0.033,
        0.6,
    ),
    SignatureAbsenceSpec(
        "deferred_tax",
        (
            "deferred tax",
            "deferred tax assets",
            "deferred tax liabilities",
            "total deferred tax assets",
            "total deferred tax liabilities",
            "net deferred tax assets",
            "net operating loss carryforwards",
        ),
        0.111,
        0.789,
    ),
    SignatureAbsenceSpec(
        "ppe",
        ("accumulated depreciation", "leasehold improvements", "land"),
        0.125,
        0.786,
    ),
    SignatureAbsenceSpec(
        "stock_comp_rollforward",
        ("granted", "forfeited", "exercised", "vested"),
        0.0,
        0.895,
    ),
    SignatureAbsenceSpec(
        "tax_reconciliation",
        ("statutory rate", "valuation allowance", "change in valuation allowance"),
        0.125,
        1.0,
    ),
)

SIGNATURE_ABSENCE_SPECS_BY_TEST_ID: dict[str, SignatureAbsenceSpec] = {
    f"{spec.family}_signature_absence": spec for spec in SIGNATURE_ABSENCE_SPECS
}

PRED_NOTES_ISOLATED = "notes_isolated"
PRED_DEEP_NOTES = "deep_notes"
PRED_ISOLATED_DEEP_NOTES = "isolated_deep_notes"


@dataclass(frozen=True, slots=True)
class PlacementSpec:
    """One family's priced imposter placement conjunction (Step 2).
    Passes when the conjunction does not fire on the table's
    placement facts; fire rates are member/false, as priced."""

    family: str
    predicate: str
    member_fire_rate: float
    false_fire_rate: float
    provenance: str = PROV_STEP2_PRICING


# Placement-conjunction specs, priced per family (Step 1
# placement lane, verified on its per-specimen feature base).
PLACEMENT_SPECS: tuple[PlacementSpec, ...] = (
    PlacementSpec("balance_sheet", PRED_NOTES_ISOLATED, 0.067, 0.494),
    PlacementSpec("comprehensive_income", PRED_DEEP_NOTES, 0.286, 0.9),
    PlacementSpec("eps_reconciliation", PRED_DEEP_NOTES, 0.0, 0.522),
    PlacementSpec("income_statement", PRED_DEEP_NOTES, 0.0, 0.478),
    PlacementSpec("segment_reporting", PRED_ISOLATED_DEEP_NOTES, 0.231, 0.636),
)

PLACEMENT_SPECS_BY_TEST_ID: dict[str, PlacementSpec] = {
    f"{spec.family}_placement": spec for spec in PLACEMENT_SPECS
}
