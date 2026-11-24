"""Form-signal spec registry: the Step 2 kinds' parameter tables.

Row bounds, signature-absence sets, and placement conjunctions,
each carrying its priced member/false rates over the v3 base.
"""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.engine.tables.extraction.core.subjects.profile_constants import (
    PROV_S1_PRICING,
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


@dataclass(frozen=True, slots=True)
class SummarySeparatorSpec:
    """One priced statement-summary separator rule (S1 pricing).
    A conjunction of feature atoms over a table's context; a fire
    denies every family claim on the geometry."""

    rule_id: str
    sub_mass: str
    atoms: tuple[str, ...]
    kills_f: int
    touches_f: int
    kills_s: int
    touches_s: int
    provenance: str = PROV_S1_PRICING


# The S1 covers of record: SELECTED-DATA pooled cap-0, MD&A-SUMMARY
# leg cap-0 covers plus the composed loc_item7/rows<=12 cell, and
# the QUARTERLY named rule (s1price run 2).
SUMMARY_SEPARATOR_SPECS: tuple[SummarySeparatorSpec, ...] = (
    SummarySeparatorSpec(
        "selected_data_present_data_years4",
        "SELECTED-DATA",
        ("present[data]", "years>=4"),
        3,
        0,
        6,
        0,
    ),
    SummarySeparatorSpec(
        "selected_data_total_assets_years3",
        "SELECTED-DATA",
        ("present[total assets]", "years>=3"),
        2,
        0,
        1,
        0,
    ),
    SummarySeparatorSpec(
        "selected_data_last_total_item6",
        "SELECTED-DATA",
        ("last_stub_total", "loc_item6"),
        1,
        0,
        0,
        0,
    ),
    SummarySeparatorSpec(
        "mda_item7_rows12_years3",
        "MD&A-SUMMARY",
        ("loc_item7", "rows<=12", "years>=3"),
        4,
        0,
        0,
        0,
    ),
    SummarySeparatorSpec(
        "mda_item2_data",
        "MD&A-SUMMARY",
        ("loc_item2", "present[data]"),
        3,
        0,
        0,
        0,
    ),
    SummarySeparatorSpec(
        "mda_item2_sales",
        "MD&A-SUMMARY",
        ("loc_item2", "present[sales]"),
        3,
        0,
        4,
        0,
    ),
    SummarySeparatorSpec(
        "mda_cols6_activities_rows12",
        "MD&A-SUMMARY",
        ("cols<=6", "present[activities]", "rows<=12", "loc_item2"),
        3,
        0,
        0,
        0,
    ),
    SummarySeparatorSpec(
        "mda_item7_summar_lead",
        "MD&A-SUMMARY",
        ("loc_item7", "summar_lead"),
        2,
        0,
        1,
        0,
    ),
    SummarySeparatorSpec(
        "mda_item2_income_tax_rows12",
        "MD&A-SUMMARY",
        ("loc_item2", "present[income tax]", "rows<=12"),
        2,
        0,
        0,
        0,
    ),
    SummarySeparatorSpec(
        "mda_item2_net_loss",
        "MD&A-SUMMARY",
        ("loc_item2", "present[net loss]"),
        1,
        0,
        0,
        0,
    ),
    SummarySeparatorSpec(
        "mda_item7_income_tax_rows12",
        "MD&A-SUMMARY",
        ("loc_item7", "present[income tax]", "rows<=12"),
        1,
        0,
        0,
        0,
    ),
    SummarySeparatorSpec(
        "mda_item7_net_income_rows12",
        "MD&A-SUMMARY",
        ("loc_item7", "present[net income]", "rows<=12"),
        1,
        0,
        0,
        0,
    ),
    SummarySeparatorSpec(
        "mda_financing_operating_rows11",
        "MD&A-SUMMARY",
        (
            "present[financing activities]",
            "present[operating activities]",
            "rows<=11",
        ),
        0,
        0,
        12,
        0,
    ),
    SummarySeparatorSpec(
        "mda_item7_sales",
        "MD&A-SUMMARY",
        ("loc_item7", "present[sales]"),
        0,
        0,
        5,
        0,
    ),
    SummarySeparatorSpec(
        "mda_total_row_item2_net_loss",
        "MD&A-SUMMARY",
        ("has_total_row", "loc_item2", "present[net loss]"),
        0,
        0,
        3,
        0,
    ),
    SummarySeparatorSpec(
        "mda_item2_financing_activities",
        "MD&A-SUMMARY",
        ("loc_item2", "present[financing activities]"),
        0,
        0,
        2,
        0,
    ),
    SummarySeparatorSpec(
        "mda_item2_operating_activities",
        "MD&A-SUMMARY",
        ("loc_item2", "present[operating activities]"),
        0,
        0,
        1,
        0,
    ),
    SummarySeparatorSpec(
        "mda_item7_condensed",
        "MD&A-SUMMARY",
        ("loc_item7", "present[condensed]"),
        0,
        0,
        1,
        0,
    ),
    SummarySeparatorSpec(
        "mda_item7_income_tax",
        "MD&A-SUMMARY",
        ("loc_item7", "present[income tax]", "rows<=12"),
        0,
        0,
        1,
        0,
    ),
    SummarySeparatorSpec(
        "mda_item7_investing_activities",
        "MD&A-SUMMARY",
        ("loc_item7", "present[investing activities]"),
        0,
        0,
        1,
        0,
    ),
    SummarySeparatorSpec(
        "mda_gross_profit_rows12",
        "MD&A-SUMMARY",
        ("present[gross profit]", "rows<=12"),
        0,
        0,
        1,
        0,
    ),
    SummarySeparatorSpec(
        "mda_net_loss_summar_lead",
        "MD&A-SUMMARY",
        ("present[net loss]", "summar_lead", "rows<=12"),
        0,
        0,
        1,
        0,
    ),
    # The quarterly-information guard on the is9
    # release: a quarterly results summary under
    # quarter heads is a summary, not a member.
    SummarySeparatorSpec(
        "mda_quarterly_information",
        "MD&A-SUMMARY",
        ("present[summary of quarterly information]", "qtr_hdr"),
        0,
        0,
        0,
        0,
    ),
    SummarySeparatorSpec(
        "mda_item2_cash_equivalents_data",
        "MD&A-SUMMARY",
        (
            "loc_item2",
            "present[cash and cash equivalents]",
            "present[data]",
        ),
        0,
        0,
        1,
        0,
    ),
    SummarySeparatorSpec(
        "mda_item7_rows12",
        "MD&A-SUMMARY",
        ("loc_item7", "rows<=12"),
        2,
        1,
        0,
        0,
    ),
    SummarySeparatorSpec(
        "quarterly_item8_total_revenues",
        "QUARTERLY",
        ("loc_item8", "present[total revenues]", "qtr_hdr"),
        0,
        0,
        2,
        0,
    ),
    # The NONGAAP-SUMMARY legs (F7 combination pricing,
    # greenfield-ci-f7combo-price run): the
    # non-GAAP prose marker conjoined with one separator
    # atom each; priced on the imposter-census claim base
    # (517 falses / 2,310 trues), counts in the seat
    # slots. Union of record: 12 kills / 2 touches.
    SummarySeparatorSpec(
        "nongaap_income_tax",
        "NONGAAP-SUMMARY",
        ("nongaap_prose", "present[income tax]"),
        0,
        0,
        8,
        1,
    ),
    SummarySeparatorSpec(
        "nongaap_years3",
        "NONGAAP-SUMMARY",
        ("nongaap_prose", "years>=3"),
        0,
        0,
        4,
        0,
    ),
    SummarySeparatorSpec(
        "nongaap_rows12",
        "NONGAAP-SUMMARY",
        ("nongaap_prose", "rows<=12"),
        0,
        0,
        5,
        1,
    ),
)

SUMMARY_SEPARATOR_SPECS_BY_ID: dict[str, SummarySeparatorSpec] = {
    spec.rule_id: spec for spec in SUMMARY_SEPARATOR_SPECS
}
