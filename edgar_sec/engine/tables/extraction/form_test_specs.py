"""Form-test spec registry: the declared specs for every kind.

Companion to the family-profile registry: profiles declare
which kinds a family carries; the specs themselves live here,
each kind's parameter table in its per-kind specs module.
"""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.domain.commodity_terms import (
    COMMODITY_HEADER_PHRASE,
    COMMERCIAL_TERMS,
    NPNS_PHRASES,
)
from edgar_sec.engine.tables.extraction.form_signal_specs import (
    FORM_SIGNAL_TEST_ENTRIES,
)
from edgar_sec.engine.tables.extraction.profiles import (
    PROV_CI_STEP6_PRICING,
    PROV_ARO_BASE,
    PROV_DECLARED_SPECS,
    PROV_DERIVATIVES_EVIDENCE,
    PROV_FAMILY_SUPPORT,
    PROV_RESTRUCTURING_PRICING,
    PROV_R18_SEAT_PRICING,
    PROV_RULING18_PRICING,
    PROV_S6B_PRICING,
    PROV_S5_SEAT_PRICING,
    PROV_STEP2_PRICING,
    PROV_STEP3_PRICING,
    PROV_WARRANTY_PRICING,
    PROV_STEP7_PRICING,
    TEST_ARO_EVIDENCE,
    TEST_ADMISSION_EVIDENCE,
    TEST_COMPOSITION_TWIN,
    TEST_CREDIT_LOSSES_EVIDENCE,
    TEST_DERIVATIVES_EVIDENCE,
    TEST_EPS_EVIDENCE,
    TEST_INVENTORY_EVIDENCE,
    TEST_LABOR_FORM,
    TEST_LADDER,
    TEST_LEASE_EVIDENCE,
    TEST_MEASURE_SET,
    TEST_PERCENTAGE_FORM,
    TEST_PLACEMENT_CONSISTENCY,
    TEST_PPE_EVIDENCE,
    TEST_PRIMARY_STATEMENT_SEAT,
    TEST_RESTRUCTURING_EVIDENCE,
    TEST_ROW_BOUND,
    TEST_SIGNATURE_ABSENCE,
    TEST_TAX_EVIDENCE,
    TEST_STOCK_COMP_EVIDENCE,
    TEST_WALK,
    TEST_WARRANTY_EVIDENCE,
)
from edgar_sec.engine.tables.extraction.aoci_claim_shape_specs import (
    AOCI_CLAIM_SHAPE_SPEC,
    AociClaimShapeSpec,
)
from edgar_sec.engine.tables.extraction.composition_specs import (
    COMPOSITION_SPECS,
    COMPOSITION_SPECS_BY_FAMILY,
    CompositionSpec,
    composition_spec_for,
)
from edgar_sec.engine.tables.extraction.derivatives_evidence_specs import (
    DERIVATIVES_EVIDENCE_SPECS,
    DERIVATIVES_EVIDENCE_SPECS_BY_TEST_ID,
    DerivativesEvidenceSpec,
)
from edgar_sec.engine.tables.extraction.percentage_form_specs import (
    PERCENTAGE_SPECS,
    PERCENTAGE_SPECS_BY_FAMILY,
    PercentageFormSpec,
)
from edgar_sec.engine.tables.extraction.seat_test_specs import (
    SEAT_REGION_BODY,
    SEAT_TEST_SPECS_BY_FAMILY,
    SeatTestSpec,
    seat_test_spec_for,
)
from edgar_sec.engine.tables.extraction.tax_evidence_specs import (
    TAX_EVIDENCE_SPECS,
    TAX_EVIDENCE_SPECS_BY_TEST_ID,
    TaxEvidenceSpec,
)
from edgar_sec.engine.tables.extraction.walk_specs import (
    WALK_SPECS_BY_TEST_ID,
    WalkSpec,
)
from edgar_sec.engine.tables.extraction.year_ladder_specs import (
    ANCHOR_AFTER_ASOF,
    ANCHOR_NONE,
    ORIENT_COLUMNS,
    ORIENT_ROWS,
    THEREAFTER_NONE,
    THEREAFTER_PREFERRED,
    THEREAFTER_REQUIRED,
    TOTAL_CORROBORATE,
    TOTAL_IGNORE,
    YEAR_LADDER_SPECS,
    YearLadderSpec,
)


__all__ = (
    "ANCHOR_AFTER_ASOF",
    "ANCHOR_NONE",
    "AOCI_CLAIM_SHAPE_SPEC",
    "AociClaimShapeSpec",
    "COMMERCIAL_TERMS",
    "COMMODITY_HEADER_PHRASE",
    "COMPOSITION_SPECS",
    "COMPOSITION_SPECS_BY_FAMILY",
    "CompositionSpec",
    "DERIVATIVES_EVIDENCE_SPECS",
    "DERIVATIVES_EVIDENCE_SPECS_BY_TEST_ID",
    "DerivativesEvidenceSpec",
    "FORM_SIGNAL_TEST_ENTRIES",
    "FORM_TEST_SPECS",
    "FORM_TEST_SPECS_BY_FAMILY",
    "FormTestSpec",
    "LADDER_SPECS_BY_TEST_ID",
    "NPNS_PHRASES",
    "ORIENT_COLUMNS",
    "ORIENT_ROWS",
    "PERCENTAGE_SPECS",
    "PERCENTAGE_SPECS_BY_FAMILY",
    "PROV_ARO_BASE",
    "PROV_CI_STEP6_PRICING",
    "PROV_DECLARED_SPECS",
    "PROV_DERIVATIVES_EVIDENCE",
    "PROV_FAMILY_SUPPORT",
    "PROV_R18_SEAT_PRICING",
    "PROV_RESTRUCTURING_PRICING",
    "PROV_RULING18_PRICING",
    "PROV_S6B_PRICING",
    "PROV_STEP2_PRICING",
    "PROV_STEP3_PRICING",
    "PROV_STEP7_PRICING",
    "PROV_WARRANTY_PRICING",
    "PercentageFormSpec",
    "SEAT_REGION_BODY",
    "SEAT_TEST_SPECS_BY_FAMILY",
    "SeatTestSpec",
    "TAX_EVIDENCE_SPECS",
    "TAX_EVIDENCE_SPECS_BY_TEST_ID",
    "TEST_ADMISSION_EVIDENCE",
    "TEST_ARO_EVIDENCE",
    "TEST_COMPOSITION_TWIN",
    "TEST_DERIVATIVES_EVIDENCE",
    "TEST_EPS_EVIDENCE",
    "TEST_INVENTORY_EVIDENCE",
    "TEST_LABOR_FORM",
    "TEST_LADDER",
    "TEST_LEASE_EVIDENCE",
    "TEST_MEASURE_SET",
    "TEST_PERCENTAGE_FORM",
    "TEST_PLACEMENT_CONSISTENCY",
    "TEST_PPE_EVIDENCE",
    "TEST_PRIMARY_STATEMENT_SEAT",
    "TEST_RESTRUCTURING_EVIDENCE",
    "TEST_ROW_BOUND",
    "TEST_SIGNATURE_ABSENCE",
    "TEST_STOCK_COMP_EVIDENCE",
    "TEST_TAX_EVIDENCE",
    "TEST_WALK",
    "TEST_WARRANTY_EVIDENCE",
    "THEREAFTER_NONE",
    "THEREAFTER_PREFERRED",
    "THEREAFTER_REQUIRED",
    "TOTAL_CORROBORATE",
    "TOTAL_IGNORE",
    "TaxEvidenceSpec",
    "WALK_SPECS_BY_TEST_ID",
    "WalkSpec",
    "YEAR_LADDER_SPECS",
    "YearLadderSpec",
    "composition_spec_for",
    "form_test_specs_for",
    "seat_test_spec_for",
)


@dataclass(frozen=True, slots=True)
class FormTestSpec:
    """One form test as registry data: the cross-kind fields only.
    Label anchors ride here where the kind uses them; each kind's
    own parameters live in its per-kind table keyed by test_id."""

    family: str
    kind: str
    test_id: str
    points: float
    beginning: tuple[str, ...] = ()
    ending: tuple[str, ...] = ()
    excluded: tuple[str, ...] = ()
    provenance: str = PROV_DECLARED_SPECS


# Form-test specs: every kind's declared specs, per family.
# A walk passes when the table's own beginning balance plus its
# movement rows reconciles to its ending balance within tolerance.
FORM_TEST_SPECS: tuple[FormTestSpec, ...] = (
    FormTestSpec(
        "aoci_rollforward",
        TEST_WALK,
        "aoci_beginning_ending_walk",
        3.0,
        beginning=(
            "beginning balance",
            "balance at beginning",
            "balance, beginning",
            "balance at january",
            "at beginning of period",
            "at beginning of year",
        ),
        ending=(
            "ending balance",
            "balance at end",
            "balance, end",
            "balance at december",
            "at end of period",
            "at end of year",
        ),
    ),
    FormTestSpec(
        "comprehensive_income",
        TEST_WALK,
        "comprehensive_income_boundary_walk",
        3.0,
        beginning=("net income", "net loss", "net earnings"),
        ending=(
            "comprehensive income",
            "comprehensive loss",
            "total comprehensive",
        ),
        excluded=("attributable to",),
    ),
    FormTestSpec(
        "stock_comp_rollforward",
        TEST_WALK,
        "stock_comp_activity_walk",
        3.0,
        beginning=(
            "outstanding at beginning",
            "outstanding at january",
            "balance at beginning",
            "beginning balance",
            "nonvested at beginning",
            "at beginning of year",
            "at beginning of period",
        ),
        ending=(
            "outstanding at end",
            "outstanding at december",
            "balance at end",
            "ending balance",
            "at end of year",
            "at end of period",
        ),
        excluded=("exercisable", "expected to vest", "available for future"),
    ),
    FormTestSpec(
        "stock_comp_rollforward",
        TEST_STOCK_COMP_EVIDENCE,
        "stock_comp_evidence",
        3.0,
        provenance=PROV_R18_SEAT_PRICING,
    ),
    FormTestSpec(
        "credit_losses_rollforward",
        TEST_CREDIT_LOSSES_EVIDENCE,
        "credit_losses_rollforward_evidence",
        3.0,
        provenance=PROV_S5_SEAT_PRICING,
    ),
    FormTestSpec(
        "eps_reconciliation",
        TEST_WALK,
        "eps_numerator_denominator_walk",
        3.0,
        beginning=("basic",),
        ending=("diluted",),
        excluded=("per share", "antidilutive", "anti-dilutive"),
    ),
    FormTestSpec(
        "eps_reconciliation",
        TEST_EPS_EVIDENCE,
        "eps_evidence",
        3.0,
        provenance=PROV_R18_SEAT_PRICING,
    ),
    FormTestSpec(
        "debt_maturity",
        TEST_LADDER,
        "debt_maturity_year_ladder",
        3.0,
    ),
    FormTestSpec(
        "commitments_contingencies",
        TEST_LADDER,
        "commitments_contingencies_year_ladder",
        3.0,
    ),
    FormTestSpec(
        "debt_maturity",
        TEST_ADMISSION_EVIDENCE,
        "debt_maturity_j1_admission",
        0.0,
        provenance=PROV_STEP7_PRICING,
    ),
    FormTestSpec(
        "commitments_contingencies",
        TEST_ADMISSION_EVIDENCE,
        "commitments_joint_admission",
        0.0,
        provenance=PROV_STEP7_PRICING,
    ),
    FormTestSpec(
        "tax_reconciliation",
        TEST_PERCENTAGE_FORM,
        "tax_rate_reconciliation_percentage_form",
        3.0,
    ),
    FormTestSpec(
        "balance_sheet",
        TEST_PRIMARY_STATEMENT_SEAT,
        "balance_sheet_either_form",
        3.0,
    ),
    FormTestSpec(
        "cash_flow",
        TEST_PRIMARY_STATEMENT_SEAT,
        "cash_flow_with_fx_leg",
        3.0,
    ),
    FormTestSpec(
        "income_statement",
        TEST_PRIMARY_STATEMENT_SEAT,
        "revenue_to_net_income_descent",
        3.0,
    ),
    FormTestSpec(
        "equity_statement",
        TEST_PRIMARY_STATEMENT_SEAT,
        "equity_column_walk",
        3.0,
    ),
    FormTestSpec("pension", TEST_COMPOSITION_TWIN, "pension_composition", 3.0),
    FormTestSpec("ppe", TEST_COMPOSITION_TWIN, "ppe_composition", 3.0),
    FormTestSpec(
        "ppe",
        TEST_PPE_EVIDENCE,
        "ppe_evidence",
        3.0,
        provenance=PROV_R18_SEAT_PRICING,
    ),
    FormTestSpec("intangibles", TEST_COMPOSITION_TWIN, "intangibles_composition", 3.0),
    FormTestSpec(
        "deferred_tax", TEST_COMPOSITION_TWIN, "deferred_tax_composition", 3.0
    ),
    FormTestSpec("inventory", TEST_COMPOSITION_TWIN, "inventory_composition", 3.0),
    FormTestSpec(
        "inventory",
        TEST_INVENTORY_EVIDENCE,
        "inventory_evidence",
        3.0,
        provenance=PROV_R18_SEAT_PRICING,
    ),
    FormTestSpec(
        "lease_maturity", TEST_COMPOSITION_TWIN, "lease_maturity_composition", 3.0
    ),
    FormTestSpec(
        "lease_maturity",
        TEST_LEASE_EVIDENCE,
        "lease_evidence",
        3.0,
        provenance=PROV_R18_SEAT_PRICING,
    ),
    FormTestSpec("fair_value", TEST_COMPOSITION_TWIN, "fair_value_composition", 3.0),
    FormTestSpec(
        "derivatives_hedging",
        TEST_DERIVATIVES_EVIDENCE,
        "derivatives_hedging_evidence_gate",
        0.0,
        provenance=PROV_DERIVATIVES_EVIDENCE,
    ),
    FormTestSpec(
        "aro_rollforward",
        TEST_ARO_EVIDENCE,
        "aro_rollforward_evidence_gate",
        3.0,
        provenance=PROV_ARO_BASE,
    ),
    FormTestSpec(
        "warranty",
        TEST_WARRANTY_EVIDENCE,
        "warranty_rollforward_evidence",
        3.0,
        provenance=PROV_WARRANTY_PRICING,
    ),
    FormTestSpec(
        "tax_reconciliation",
        TEST_TAX_EVIDENCE,
        "tax_reconciliation_statutory_anchor_seat",
        0.0,
        provenance=PROV_RULING18_PRICING,
    ),
    FormTestSpec(
        "labor_contracts",
        TEST_LABOR_FORM,
        "labor_contracts_form",
        0.0,
        provenance=PROV_S6B_PRICING,
    ),
    FormTestSpec(
        "shares_purchased",
        TEST_MEASURE_SET,
        "shares_purchased_measure_set",
        3.0,
        provenance=PROV_STEP3_PRICING,
    ),
    FormTestSpec(
        "valuation_model_assumptions",
        TEST_MEASURE_SET,
        "valuation_model_assumptions_measure_set",
        3.0,
        provenance=PROV_STEP3_PRICING,
    ),
    FormTestSpec(
        "warrant_activity",
        TEST_MEASURE_SET,
        "warrant_activity_rollforward",
        3.0,
        provenance=PROV_STEP3_PRICING,
    ),
    FormTestSpec(
        "warrant_activity",
        TEST_MEASURE_SET,
        "warrant_outstanding_listing",
        3.0,
        provenance=PROV_STEP3_PRICING,
    ),
    FormTestSpec(
        "combined_operations_ci",
        TEST_MEASURE_SET,
        "combined_operations_ci_measure_set",
        3.0,
        provenance=PROV_CI_STEP6_PRICING,
    ),
    FormTestSpec(
        "combined_operations_ci",
        TEST_MEASURE_SET,
        "combined_operations_ci_joint_measure_set",
        3.0,
        provenance=PROV_CI_STEP6_PRICING,
    ),
    FormTestSpec(
        "restructuring",
        TEST_RESTRUCTURING_EVIDENCE,
        "restructuring_rollforward_evidence",
        3.0,
        provenance=PROV_RESTRUCTURING_PRICING,
    ),
    *(
        FormTestSpec(family, kind, test_id, points, provenance=PROV_STEP2_PRICING)
        for family, kind, test_id, points in FORM_SIGNAL_TEST_ENTRIES
    ),
)


# The same parameters keyed by test_id, derived at registry load
# for the stage adapter; never a second literal copy. Ladder-kind
# specs only — other kinds over a ladder family stay out.
LADDER_SPECS_BY_TEST_ID: dict[str, YearLadderSpec] = {
    spec.test_id: YEAR_LADDER_SPECS[spec.family]
    for spec in FORM_TEST_SPECS
    if spec.kind == TEST_LADDER and spec.family in YEAR_LADDER_SPECS
}


FORM_TEST_SPECS_BY_FAMILY: dict[str, tuple[FormTestSpec, ...]] = {}
for _spec in FORM_TEST_SPECS:
    FORM_TEST_SPECS_BY_FAMILY[_spec.family] = (
        *FORM_TEST_SPECS_BY_FAMILY.get(_spec.family, ()),
        _spec,
    )


def form_test_specs_for(family: str) -> tuple[FormTestSpec, ...]:
    """The declared form-test specs for a family; none if undeclared."""
    return FORM_TEST_SPECS_BY_FAMILY.get(family, ())
