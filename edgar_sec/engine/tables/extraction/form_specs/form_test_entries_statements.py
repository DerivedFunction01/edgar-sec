"""Form-test entries: walks, ladders, admissions, and the
primary statement seats — the statement-form block of the
registry, composed into FORM_TEST_SPECS by form_test_specs.
"""

from __future__ import annotations

from edgar_sec.engine.tables.extraction.form_specs.form_test_types import FormTestSpec
from edgar_sec.engine.tables.extraction.core.subjects.profiles import (
    PROV_EPS_REFUSAL_PRICING,
    PROV_EPS_TRANSFER_PRICING,
    PROV_R18_SEAT_PRICING,
    PROV_S5_SEAT_PRICING,
    PROV_STEP7_PRICING,
    TEST_ADMISSION_EVIDENCE,
    TEST_CREDIT_LOSSES_EVIDENCE,
    TEST_EPS_DETECTOR,
    TEST_EPS_EVIDENCE,
    TEST_LADDER,
    TEST_PERCENTAGE_FORM,
    TEST_PRIMARY_STATEMENT_SEAT,
    TEST_STOCK_COMP_EVIDENCE,
    TEST_WALK,
)
from edgar_sec.engine.tables.extraction.form_specs.eps_refusal_specs import (
    EPS_REFUSAL_TEST_ENTRIES,
)

STATEMENT_FORM_TEST_ENTRIES: tuple[FormTestSpec, ...] = (
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
        "eps_reconciliation",
        TEST_EPS_DETECTOR,
        "eps_detector",
        0.0,
        provenance=PROV_EPS_TRANSFER_PRICING,
    ),
    *(
        FormTestSpec(family, kind, test_id, points, provenance=PROV_EPS_REFUSAL_PRICING)
        for family, kind, test_id, points in EPS_REFUSAL_TEST_ENTRIES
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
)
