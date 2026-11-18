"""Form-test spec registry: the declared specs for every kind.

Companion to the family-profile registry: profiles declare
which kinds a family carries; the specs themselves, and each
kind's parameter table, live here as data.
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


@dataclass(frozen=True, slots=True)
class WalkSpec:
    """Walk-kind parameters for one test, keyed by test_id below.
    column_headers selects value columns (empty means all of them);
    a pass needs min_columns columns closed over >= min_movements."""

    min_movements: int = 1
    min_columns: int = 1
    column_headers: tuple[str, ...] = ()


ORIENT_COLUMNS = "columns"
ORIENT_ROWS = "rows"
THEREAFTER_REQUIRED = "required"
THEREAFTER_PREFERRED = "preferred"
THEREAFTER_NONE = "none"
TOTAL_CORROBORATE = "corroborate"
TOTAL_IGNORE = "ignore"
ANCHOR_AFTER_ASOF = "after_asof_when_present"
ANCHOR_NONE = "none"


@dataclass(frozen=True, slots=True)
class YearLadderSpec:
    """Year-ladder form-test parameters, declared as registry data."""

    orientations: tuple[str, ...]
    min_year_steps: int
    thereafter: str = THEREAFTER_PREFERRED
    bucket_ladder: bool = False
    min_bucket_steps: int = 0
    total_mode: str = TOTAL_CORROBORATE
    anchor: str = ANCHOR_AFTER_ASOF
    tolerance: float = 0.02


@dataclass(frozen=True, slots=True)
class PercentageFormSpec:
    """One family's percentage-form test, declared as data."""

    family: str
    anchor_tokens: tuple[str, ...]
    total_tokens: tuple[str, ...]
    min_adjustments: int = 1
    closure_tolerance: float = 0.3
    min_columns: int = 1


@dataclass(frozen=True, slots=True)
class CompositionSpec:
    """One family's composition-twin test, declared as data.

    Passes a table enumerating the family's component classes
    with amounts per class; fails totals-only summaries.
    """

    family: str
    stub_groups: tuple[tuple[str, ...], ...]
    min_stub_groups: int
    min_class_rows: int
    column_groups: tuple[tuple[str, ...], ...] = ()
    min_column_groups: int = 0
    orientation: str = "rows"
    period_columns: bool = False
    total_terms: tuple[str, ...] = ()
    refused_shapes: tuple[str, ...] = ()
    provenance: str = PROV_FAMILY_SUPPORT


# The primary-statement seat (class iv): a statement table
# sits in the body region, outside the TOC and closing spans —
# the seat facts the context production carries.
SEAT_REGION_BODY = "body"


@dataclass(frozen=True, slots=True)
class SeatTestSpec:
    """One primary-statement seat test, declared as registry data.

    The seat facts must hold on the context, and the named
    identity must close over the table's own total rows.
    """

    identity: str
    required_roles: tuple[str, ...]
    ordered_roles: tuple[str, ...] = ()
    either_roles: tuple[tuple[str, ...], ...] = ()
    optional_roles: tuple[str, ...] = ()
    seat_region: str = SEAT_REGION_BODY
    in_toc_span: bool = False
    in_closing_span: bool = False
    tolerance_abs: float = 2.0
    tolerance_rel: float = 0.005


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


@dataclass(frozen=True, slots=True)
class AociClaimShapeSpec:
    """AOCI claim shape (Step 9 pricing): the subject leg's terms.
    A standalone aoci_rollforward claim requires the family's core
    shape: a beginning-to-ending walk plus an AOCI subject."""

    component_terms: tuple[str, ...]
    min_components: int = 2
    subject_phrase: str = "other comprehensive"
    lead_phrase: str = "accumulated other comprehensive"
    provenance: str = "step9:aoci-claim-shape-pricing"


AOCI_CLAIM_SHAPE_SPEC = AociClaimShapeSpec(
    component_terms=(
        "foreign currency",
        "cash flow hedge",
        "derivative",
        "defined benefit",
        "pension",
        "postretirement",
        "available-for-sale",
        "available for sale",
        "debt securities",
        "securities",
        "unrealized",
        "translation",
        "hedg",
    ),
)


# Walk-kind parameters, keyed by test_id (the per-kind table).
WALK_SPECS_BY_TEST_ID: dict[str, WalkSpec] = {
    "aoci_beginning_ending_walk": WalkSpec(),
    "comprehensive_income_boundary_walk": WalkSpec(),
    "stock_comp_activity_walk": WalkSpec(),
    "eps_numerator_denominator_walk": WalkSpec(min_columns=2),
}

# Year-ladder class specs, keyed by family: the one literal
# home of the ladder kind's parameters.
YEAR_LADDER_SPECS: dict[str, YearLadderSpec] = {
    "debt_maturity": YearLadderSpec(
        orientations=(ORIENT_COLUMNS, ORIENT_ROWS),
        min_year_steps=4,
        thereafter=THEREAFTER_PREFERRED,
        bucket_ladder=False,
        total_mode=TOTAL_CORROBORATE,
        anchor=ANCHOR_AFTER_ASOF,
    ),
    "commitments_contingencies": YearLadderSpec(
        orientations=(ORIENT_COLUMNS, ORIENT_ROWS),
        min_year_steps=3,
        thereafter=THEREAFTER_PREFERRED,
        bucket_ladder=True,
        min_bucket_steps=3,
        total_mode=TOTAL_CORROBORATE,
        anchor=ANCHOR_AFTER_ASOF,
    ),
}

# The same parameters keyed by test_id, derived at registry load
# for the stage adapter; never a second literal copy. Ladder-kind
# specs only — other kinds over a ladder family stay out.
LADDER_SPECS_BY_TEST_ID: dict[str, YearLadderSpec] = {
    spec.test_id: YEAR_LADDER_SPECS[spec.family]
    for spec in FORM_TEST_SPECS
    if spec.kind == TEST_LADDER and spec.family in YEAR_LADDER_SPECS
}

# Percentage-form specs (class (iii)): one per family
# declaring TEST_PERCENTAGE_FORM, pinned from the measured
# directed sets and the adjudicated specimens in each note.
PERCENTAGE_SPECS: tuple[PercentageFormSpec, ...] = (
    PercentageFormSpec(
        "tax_reconciliation",
        anchor_tokens=(
            "statutory rate",
            "statutory tax",
            "at statutory",
            "statutory federal",
            "federal statutory",
        ),
        total_tokens=(
            "effective tax",
            "effective income tax",
            "effective rate",
        ),
        min_adjustments=1,
        closure_tolerance=0.3,
    ),
)

PERCENTAGE_SPECS_BY_FAMILY = {spec.family: spec for spec in PERCENTAGE_SPECS}

# Primary-statement seat specs (class (iv)), keyed by family:
# the one literal home of the seat kind's parameters.
SEAT_TEST_SPECS_BY_FAMILY: dict[str, SeatTestSpec] = {
    "balance_sheet": SeatTestSpec(
        identity="balance_sheet_either_form",
        required_roles=("total_assets",),
        either_roles=(("total_liabilities", "total_equity"), ("combined",)),
    ),
    "cash_flow": SeatTestSpec(
        identity="cash_flow_with_fx_leg",
        required_roles=("operating", "investing", "financing", "change"),
        ordered_roles=("operating", "investing", "financing", "change"),
        optional_roles=("fx", "cash_beginning", "cash_ending"),
    ),
    "equity_statement": SeatTestSpec(
        identity="equity_column_walk",
        required_roles=(
            "beginning_balance",
            "movement",
            "ending_balance",
            "component_columns",
            "total_column",
        ),
        ordered_roles=("beginning_balance", "ending_balance"),
    ),
    "income_statement": SeatTestSpec(
        identity="revenue_to_net_income_descent",
        required_roles=("revenue", "cogs", "gross_profit", "net_income"),
        ordered_roles=(
            "revenue",
            "cogs",
            "gross_profit",
            "operating_income",
            "pretax_income",
            "net_income",
        ),
        optional_roles=("operating_income", "pretax_income"),
    ),
}


def seat_test_spec_for(family: str) -> SeatTestSpec | None:
    """The family's primary-statement seat spec, or None."""
    return SEAT_TEST_SPECS_BY_FAMILY.get(family)


# Composition-twin specs (class (v)): one per family
# declaring TEST_COMPOSITION_TWIN, pinned from the directed
# sets and adjudicated specimens named in each provenance.
COMPOSITION_SPECS: tuple[CompositionSpec, ...] = (
    CompositionSpec(
        "pension",
        stub_groups=(
            ("service cost",),
            ("interest cost",),
            ("expected return on plan assets", "expected return"),
            ("amortization", "prior service"),
        ),
        min_stub_groups=3,
        min_class_rows=3,
        total_terms=("net periodic benefit cost", "net periodic pension cost"),
        refused_shapes=(
            "aoci_component_composition",
            "assumption_only",
            "single_line_summary",
            "totals_only",
        ),
        provenance="directed:t5x-pension-q",
    ),
    CompositionSpec(
        "ppe",
        stub_groups=(
            ("land",),
            ("building",),
            ("machinery",),
            ("transportation", "vehicle"),
            ("construction in progress", "construction in process"),
            ("furniture", "fixture"),
            ("leasehold",),
            ("computer",),
        ),
        min_stub_groups=3,
        min_class_rows=3,
        column_groups=(
            ("accumulated depreciation",),
            ("cost", "gross"),
            ("net",),
        ),
        min_column_groups=1,
        total_terms=("total property", "property and equipment, net"),
        refused_shapes=("totals_only", "single_line_summary", "movement_only"),
        provenance="directed:t5x-ppe",
    ),
    CompositionSpec(
        "intangibles",
        stub_groups=(
            ("backlog",),
            ("technology",),
            ("trademark", "trade name", "brand"),
            ("customer",),
            ("patent",),
            ("license", "licence"),
            ("noncompete", "non-compete", "covenant"),
            ("franchise",),
            ("supplier",),
        ),
        min_stub_groups=2,
        min_class_rows=2,
        column_groups=(
            ("gross carrying", "gross"),
            ("accumulated amortization",),
            ("net carrying", "net"),
        ),
        min_column_groups=2,
        period_columns=True,
        total_terms=("total intangible",),
        refused_shapes=(
            "totals_only",
            "purchase_price_allocation",
            "rollforward_by_category",
            "single_class_summary",
        ),
        provenance="directed:t5x-intangibles-q",
    ),
    CompositionSpec(
        "deferred_tax",
        stub_groups=(
            ("net operating loss", "loss carryforward"),
            ("tax credit", "credit carryforward"),
            ("capital loss",),
            ("accrued",),
            ("stock compensation", "share-based compensation"),
            ("valuation allowance",),
            ("depreciation",),
            ("amortization",),
            ("right-of-use", "right of use"),
            ("unrealized",),
            ("prepaid",),
        ),
        min_stub_groups=2,
        min_class_rows=2,
        total_terms=("net deferred tax", "total deferred"),
        refused_shapes=(
            "allowance_walk_only",
            "provision_detail",
            "single_line_summary",
        ),
        provenance="directed:t3-deferred_tax",
    ),
    CompositionSpec(
        "inventory",
        stub_groups=(
            ("raw material",),
            ("work in process", "work-in-process", "work in progress"),
            ("finished good",),
            ("supplies",),
            ("merchandise",),
        ),
        min_stub_groups=2,
        min_class_rows=2,
        total_terms=("total inventories", "total inventory", "inventories, net"),
        refused_shapes=("totals_only", "single_line_summary"),
        provenance="directed:t5x-inventory-q",
    ),
    CompositionSpec(
        "lease_maturity",
        stub_groups=(
            ("operating lease",),
            ("finance lease",),
            ("capital lease",),
        ),
        min_stub_groups=1,
        min_class_rows=3,
        orientation="columns",
        total_terms=(
            "total undiscounted",
            "total lease payments",
            "imputed interest",
            "total lease liabilities",
            "present value",
        ),
        refused_shapes=(
            "cost_composition_only",
            "totals_only",
            "single_line_summary",
        ),
        provenance="directed:t5x-lease_maturity",
    ),
    CompositionSpec(
        "fair_value",
        stub_groups=(
            ("level 1",),
            ("level 2",),
            ("level 3",),
            ("net asset value", "nav"),
        ),
        min_stub_groups=2,
        min_class_rows=2,
        orientation="columns",
        total_terms=("total assets", "total liabilities"),
        refused_shapes=(
            "portfolio_composition_no_levels",
            "totals_only",
            "single_line_summary",
        ),
        provenance="directed:fair_value-levels",
    ),
)

COMPOSITION_SPECS_BY_FAMILY = {spec.family: spec for spec in COMPOSITION_SPECS}


def composition_spec_for(family: str) -> CompositionSpec | None:
    """The family's composition-twin spec, or None if it has none."""
    return COMPOSITION_SPECS_BY_FAMILY.get(family)


FORM_TEST_SPECS_BY_FAMILY: dict[str, tuple[FormTestSpec, ...]] = {}
for _spec in FORM_TEST_SPECS:
    FORM_TEST_SPECS_BY_FAMILY[_spec.family] = (
        *FORM_TEST_SPECS_BY_FAMILY.get(_spec.family, ()),
        _spec,
    )


def form_test_specs_for(family: str) -> tuple[FormTestSpec, ...]:
    """The declared form-test specs for a family; none if undeclared."""
    return FORM_TEST_SPECS_BY_FAMILY.get(family, ())


@dataclass(frozen=True, slots=True)
class DerivativesEvidenceSpec:
    """Derivatives-evidence gate parameters, declared as data.
    An unambiguous base decides alone, ambiguous bases decide only
    in accumulation; the equity / NPNS lists carve subjects out."""

    family: str
    test_id: str
    unambiguous_bases: tuple[str, ...]
    ambiguous_bases: tuple[str, ...]
    stem_bases: tuple[tuple[str, str], ...]
    designation_phrases: tuple[str, ...]
    anchor_terms: tuple[str, ...]
    suffix_terms: tuple[str, ...]
    commercial_terms: tuple[str, ...]
    npns_phrases: tuple[str, ...]
    equity_comp_terms: tuple[str, ...]
    equity_prefixes: tuple[str, ...]
    aoci_subject_phrases: tuple[str, ...]
    commodity_header: str
    effects_phrases: tuple[str, ...]
    effects_leadin_phrases: tuple[str, ...]
    offsetting_phrases: tuple[str, ...]
    min_period_rows: int = 2
    provenance: str = PROV_DERIVATIVES_EVIDENCE


# Derivatives-evidence gate specs, keyed by family: the one
# literal home of the gate kind's parameters, priced against
# the measured evidence-class split over the 58 specimens.
DERIVATIVES_EVIDENCE_SPECS: dict[str, DerivativesEvidenceSpec] = {
    "derivatives_hedging": DerivativesEvidenceSpec(
        family="derivatives_hedging",
        test_id="derivatives_hedging_evidence_gate",
        unambiguous_bases=(
            "swap",
            "swaps",
            "forward",
            "forwards",
            "collar",
            "collars",
            "derivative",
            "derivatives",
            "futures",
            "swaption",
            "swaptions",
            "straddle",
            "strangle",
        ),
        ambiguous_bases=(
            "option",
            "options",
            "cap",
            "caps",
            "floor",
            "floors",
            "put",
            "puts",
            "call",
            "calls",
            "hedge",
            "hedges",
            "hedging",
            "lock",
            "locks",
        ),
        stem_bases=(("capped", "cap"),),
        designation_phrases=(
            "designated as hedging",
            "not designated",
            "designated hedging",
            "hedging instruments",
            "derivative assets",
            "derivative liabilities",
            "derivative contracts",
            "derivative instruments",
            "derivative financial instruments",
            "cash flow hedge",
            "fair value hedge",
            "net investment hedge",
            "hedge accounting",
            "derivatives designated",
        ),
        anchor_terms=(
            "notional",
            "fair value",
            "fair market value",
            "balance sheet location",
            "income statement location",
            "offsetting",
            "netting",
            "gross amounts",
            "exercise price",
        ),
        suffix_terms=("contract", "contracts", "instrument", "instruments"),
        commercial_terms=COMMERCIAL_TERMS,
        npns_phrases=NPNS_PHRASES,
        equity_comp_terms=(
            "restricted stock",
            "stock appreciation",
            "employee stock",
            "equity incentive",
            "options granted",
            "shares available for future",
            "weighted-average exercise",
            "weighted average exercise",
        ),
        equity_prefixes=("stock", "equity", "share", "dividend"),
        aoci_subject_phrases=(
            "accumulated other comprehensive income components",
            "details about accumulated other comprehensive",
        ),
        commodity_header=COMMODITY_HEADER_PHRASE,
        effects_phrases=(
            "effects of cash flow hedges",
            "effect of derivative",
            "effects of derivative",
            "effect of our derivative",
        ),
        effects_leadin_phrases=(
            "effects of cash flow hedges",
            "effect of our derivative",
        ),
        offsetting_phrases=(
            "offsetting",
            "amounts offset",
            "not offset",
            "gross amounts offset",
        ),
    ),
}

# The same parameters keyed by test_id, derived at registry load
# for the stage adapter; never a second literal copy.
DERIVATIVES_EVIDENCE_SPECS_BY_TEST_ID: dict[str, DerivativesEvidenceSpec] = {
    spec.test_id: spec for spec in DERIVATIVES_EVIDENCE_SPECS.values()
}


@dataclass(frozen=True, slots=True)
class TaxEvidenceSpec:
    """Tax seat parameters, declared as data: the priced
    conjunction's stub anchor and lead context terms, plus
    the hard-veto terms the seat outranks at its claim act."""

    family: str
    test_id: str
    stub_anchor_terms: tuple[str, ...]
    lead_context_terms: tuple[str, ...]
    seat_veto_precedence_terms: tuple[str, ...] = ()
    provenance: str = PROV_RULING18_PRICING


# Tax seat specs, keyed by family: the priced conjunction
# (Ruling 18 pass, seater P 1.000 / R .929 on fresh strata).
TAX_EVIDENCE_SPECS: dict[str, TaxEvidenceSpec] = {
    "tax_reconciliation": TaxEvidenceSpec(
        family="tax_reconciliation",
        test_id="tax_reconciliation_statutory_anchor_seat",
        stub_anchor_terms=("statutory",),
        lead_context_terms=("tax",),
        seat_veto_precedence_terms=("ended march",),
    ),
}

# The same parameters keyed by test_id, derived at registry load
# for the stage adapter; never a second literal copy.
TAX_EVIDENCE_SPECS_BY_TEST_ID: dict[str, TaxEvidenceSpec] = {
    spec.test_id: spec for spec in TAX_EVIDENCE_SPECS.values()
}
