"""Classification registry: measured values with Step 3 provenance."""

from __future__ import annotations

from dataclasses import dataclass

CALIBRATION_RECORD = "run-logs/2026-11-09-table-extraction-step3-calibration.md"
PROV_TERM_PATTERNS = "step3:term_patterns"
PROV_SEQUENCES = "step3:constitutive_sequences"
PROV_PROSE = "step3:prose_patterns"
PROV_LOCATION = "step3:location_strengths"
PROV_SHAPES = "step3:shape_bounds"
PROV_FLAVORS = "step3:flavor_census"
PROV_NEGATIVE = "step3:negative_evidence"
PROV_MATH = "step3:math_pricing"
PROV_COVERAGE_SEED = "coverage-redrive:seed-06af1209"
PROV_COVERAGE_DISCOVERY = "coverage-redrive:discovery"
PROV_CONTAINMENT = "containment:census-2026-11-10"
PROV_MATH_POINTS = "step6:identity_pricing"
PROV_REPAIR_DISCOVERY = "repair:discovery"
PROV_REPAIR_LANDMARKS = "repair:landmarks"
PROV_REPAIR_NEGATIVE = "repair:negative_evidence"
PROV_STEP8C_CENSUS = "step8c:note_census"
PROV_STEP8C_DRIVE = "step8c:context_drive"
PROV_STEP8D_CENSUS = "step8d:structure_census"
PROV_STEP8D_DRIVE = "step8d:structure_drive"

RESIDUAL_FAMILY = "other"
CORE_FAMILIES = (
    "income_statement",
    "balance_sheet",
    "cash_flow",
    "equity_statement",
)
SATELLITE_FAMILIES = (
    "deferred_tax",
    "fair_value",
    "eps_reconciliation",
    "lease_maturity",
    "inventory",
    "tax_reconciliation",
    "aoci",
    "pension",
    "stock_comp_rollforward",
    "intangibles",
    "debt_maturity",
    "derivatives_hedging",
    "ppe",
)
FAMILY_PRIORITY = (
    "eps_reconciliation",
    "tax_reconciliation",
    "deferred_tax",
    "fair_value",
    "inventory",
    "lease_maturity",
    "aoci",
    "cover_layout",
    "debt_maturity",
    "derivatives_hedging",
    "intangibles",
    "pension",
    "ppe",
    "shares_purchased",
    "stock_comp_rollforward",
    "balance_sheet",
    "cash_flow",
    "income_statement",
    "equity_statement",
    "subsequent_events",
    "segment_reporting",
    "commitments_contingencies",
    "related_party",
    "other",
)

# Cascade design constants; measured inputs enter through the specs.
LABEL_GROUP_QUOTA = 6
TOKEN_GROUP_QUOTA = 4
LANDMARK_GROUP_QUOTA = 8
PROSE_GROUP_QUOTA = 2
NOTE_GROUP_QUOTA = 1
STRUCTURE_GROUP_QUOTA = 4
NEGATIVE_GROUP_QUOTA = 2
CONTEXT_ANCHOR_MIN_SCORE = 8.0
LABEL_WEIGHT = 1.0
LABEL_EXCLUSIVITY_WEIGHT = 3.0
TOKEN_WEIGHT = 0.5
LANDMARK_POINTS = 1.5
PAIR_POINTS = 3.0
TRIPLE_POINTS = 5.0
PROSE_POINTS = 0.5
LOCATION_POINTS = 2.0
NEGATIVE_ZERO_RATE_POINTS = 6.0
NEGATIVE_PRESENT_POINTS = 3.0
SHAPE_OVERAGE_PENALTY = 2.0
SHAPE_ENVELOPE_POINTS = 0.5
SLOT_MAIN_MIN_CANDIDACY = 1.0
ASSIGNMENT_FLOOR = 5.0
MATH_GROUP_QUOTA = 1


@dataclass(frozen=True, slots=True)
class PatternSpec:
    """One measured registry entry; provenance names its source."""

    family: str
    term: str
    kind: str
    support: int
    share: float
    exclusivity: float
    provenance: str = PROV_TERM_PATTERNS


@dataclass(frozen=True, slots=True)
class SequenceSpec:
    """One measured registry entry; provenance names its source."""

    family: str
    terms: tuple[str, ...]
    support: int
    provenance: str = PROV_SEQUENCES


@dataclass(frozen=True, slots=True)
class ProsePatternSpec:
    """One measured registry entry; provenance names its source."""

    family: str
    ngram: str
    window: str
    support: int
    exclusivity: float
    provenance: str = PROV_PROSE


@dataclass(frozen=True, slots=True)
class LocationSpec:
    """One measured registry entry; provenance names its source."""

    family: str | None
    geometries: int
    items: tuple[tuple[str | None, int], ...]
    note_rate: float
    unlocated_rate: float
    provenance: str = PROV_LOCATION


@dataclass(frozen=True, slots=True)
class ShapeBound:
    """One measured registry entry; provenance names its source."""

    family: str | None
    geometries: int
    value_rows_p5: int
    value_rows_p95: int
    columns_p95: int
    columns_max: int
    assembled_rows_p5: int
    assembled_rows_p95: int
    provenance: str = PROV_SHAPES


@dataclass(frozen=True, slots=True)
class FlavorSpec:
    """One measured registry entry; provenance names its source."""

    family: str
    flavor: str
    geometries: int
    filings: int
    recurs: bool
    provenance: str = PROV_FLAVORS


@dataclass(frozen=True, slots=True)
class NegativeSpec:
    """One measured registry entry; provenance names its source."""

    evidence_family: str
    term: str
    vetoed_family: str | None
    member_presence_rate: float
    provenance: str = PROV_NEGATIVE


@dataclass(frozen=True, slots=True)
class LandmarkSpec:
    """One measured registry entry; provenance names its source."""

    family: str
    label: str
    points: float
    exclusivity: float
    provenance: str = PROV_REPAIR_LANDMARKS


@dataclass(frozen=True, slots=True)
class NoteTitleSpec:
    """A family's note home: the note title as a floor-tier claim.

    Points reach exactly the assignment floor, so the claim assigns
    only tables no scored family claims.
    """

    family: str
    phrase: str
    points: float
    exclusivity: float
    support: int
    provenance: str = PROV_STEP8C_CENSUS
    discovery: str = PROV_STEP8C_DRIVE


@dataclass(frozen=True, slots=True)
class StructureSpec:
    """One measured registry entry; provenance names its source."""

    family: str
    name: str
    points: float
    exclusivity: float
    support: int
    provenance: str = PROV_STEP8D_CENSUS
    discovery: str = PROV_STEP8D_DRIVE


STRUCTURE_SPECS: tuple[StructureSpec, ...] = (
    StructureSpec("equity_statement", "component_columns", 1.36, 0.119, 67),
    StructureSpec("equity_statement", "rollforward_grid", 1.38, 0.127, 63),
    StructureSpec("equity_statement", "movement_grid", 1.28, 0.092, 65),
    StructureSpec("equity_statement", "complete_grid", 1.35, 0.118, 34),
)


SHAPE_BOUNDS: tuple[ShapeBound, ...] = (
    ShapeBound("aoci", 8, 4, 11, 8, 8, 4, 14),
    ShapeBound("balance_sheet", 117, 7, 39, 5, 8, 13, 45),
    ShapeBound("cash_flow", 151, 4, 45, 4, 5, 12, 66),
    ShapeBound("cover_layout", 1, 1, 1, 1, 1, 1, 1),
    ShapeBound("debt_maturity", 6, 3, 9, 1, 1, 3, 9),
    ShapeBound("deferred_tax", 44, 2, 19, 3, 3, 5, 40),
    ShapeBound("derivatives_hedging", 2, 3, 8, 4, 4, 3, 8),
    ShapeBound("eps_reconciliation", 24, 4, 14, 4, 4, 4, 14),
    ShapeBound("equity_statement", 9, 8, 42, 7, 7, 16, 42),
    ShapeBound("fair_value", 18, 2, 13, 8, 8, 2, 31),
    ShapeBound("income_statement", 154, 7, 37, 6, 8, 13, 74),
    ShapeBound("intangibles", 4, 2, 9, 2, 2, 2, 9),
    ShapeBound("inventory", 18, 3, 6, 3, 3, 3, 12),
    ShapeBound("lease_maturity", 17, 2, 12, 4, 4, 2, 12),
    ShapeBound("other", 6413, 0, 23, 6, 13, 7, 820),
    ShapeBound("pension", 4, 3, 25, 3, 3, 3, 25),
    ShapeBound("ppe", 3, 3, 5, 2, 2, 3, 5),
    ShapeBound("shares_purchased", 2, 3, 3, 4, 4, 3, 3),
    ShapeBound("stock_comp_rollforward", 8, 3, 20, 4, 4, 3, 20),
    ShapeBound("tax_reconciliation", 22, 4, 15, 4, 6, 4, 15),
)
SHAPE_BOUNDS_BY_FAMILY = {spec.family: spec for spec in SHAPE_BOUNDS}

LANDMARKS: dict[str, tuple[str, ...]] = {
    "income_statement": (
        "general and administrative",
        "gross profit",
        "interest expense",
        "interest income",
        "loss from operations",
        "net income",
        "net income (loss)",
        "net loss",
        "operating expenses",
        "research and development",
        "revenues",
        "total operating expenses",
    ),
    "balance_sheet": (
        "accounts payable",
        "accumulated deficit",
        "accumulated other comprehensive loss",
        "additional paid-in capital",
        "assets",
        "cash and cash equivalents",
        "current assets",
        "current liabilities",
        "goodwill",
        "liabilities",
        "liabilities and stockholders’ equity",
        "other assets",
        "prepaid expenses and other current assets",
        "property and equipment, net",
        "retained earnings",
        "stockholders’ equity",
        "total assets",
        "total current assets",
        "total current liabilities",
        "total liabilities",
        "total liabilities and stockholders’ equity",
        "total stockholders’ equity",
    ),
    "cash_flow": (
        "accounts payable",
        "cash flows from financing activities",
        "cash flows from investing activities",
        "cash flows from operating activities",
        "changes in operating assets and liabilities",
        "depreciation and amortization",
        "financing activities",
        "investing activities",
        "net cash provided by financing activities",
        "net cash provided by operating activities",
        "net cash used in investing activities",
        "net cash used in operating activities",
        "net loss",
        "operating activities",
    ),
    "aoci": (
        "balance at end of period",
        "balance at beginning of period",
        "beginning balance",
        "ending balance",
    ),
    "equity_statement": ("foreign currency translation adjustments",),
    "stock_comp_rollforward": (
        "granted",
        "exercised",
    ),
}

LANDMARK_SPECS: tuple[LandmarkSpec, ...] = (
    LandmarkSpec("income_statement", "other income, net", 1.83, 0.667),
    LandmarkSpec("income_statement", "loss before income taxes", 1.45, 0.475),
    LandmarkSpec("income_statement", "cost of sales", 1.39, 0.446),
    LandmarkSpec("income_statement", "income before income taxes", 1.37, 0.434),
    LandmarkSpec("income_statement", "other income (expense)", 1.33, 0.414),
    LandmarkSpec(
        "income_statement", "selling, general and administrative", 1.28, 0.392
    ),
    LandmarkSpec("income_statement", "other income", 1.27, 0.387),
    LandmarkSpec("income_statement", "provision for income taxes", 1.2, 0.351),
    LandmarkSpec("income_statement", "income tax expense", 1.18, 0.338),
    LandmarkSpec("deferred_tax", "net operating loss carryforward", 1.5, 0.5),
    LandmarkSpec("deferred_tax", "less: valuation allowance", 1.2, 0.35),
    LandmarkSpec("deferred_tax", "net operating loss carryforwards", 1.11, 0.304),
    LandmarkSpec("tax_reconciliation", "u.s. federal statutory tax rate", 2.5, 1.0),
    LandmarkSpec("tax_reconciliation", "nontaxable or nondeductible items", 2.1, 0.8),
    LandmarkSpec("tax_reconciliation", "changes in valuation allowances", 2.0, 0.75),
    LandmarkSpec("tax_reconciliation", "tax credits", 1.27, 0.385),
    LandmarkSpec("eps_reconciliation", "denominator", 1.1, 0.3),
    LandmarkSpec("eps_reconciliation", "numerator", 1.1, 0.3),
    LandmarkSpec("eps_reconciliation", "basic earnings per common share", 1.1, 0.3),
)

SEQUENCES: tuple[SequenceSpec, ...] = (
    SequenceSpec(
        "income_statement", ("operating expenses", "total operating expenses"), 46
    ),
    SequenceSpec(
        "income_statement", ("operating expenses", "general and administrative"), 35
    ),
    SequenceSpec(
        "income_statement",
        ("general and administrative", "total operating expenses"),
        33,
    ),
    SequenceSpec(
        "income_statement", ("research and development", "total operating expenses"), 31
    ),
    SequenceSpec(
        "income_statement", ("operating expenses", "research and development"), 30
    ),
    SequenceSpec("income_statement", ("research and development", "net loss"), 27),
    SequenceSpec("income_statement", ("operating expenses", "net loss"), 26),
    SequenceSpec("income_statement", ("total operating expenses", "net loss"), 26),
    SequenceSpec(
        "income_statement",
        ("research and development", "general and administrative"),
        26,
    ),
    SequenceSpec("income_statement", ("gross profit", "research and development"), 25),
    SequenceSpec("income_statement", ("general and administrative", "net loss"), 25),
    SequenceSpec("income_statement", ("loss from operations", "net loss"), 24),
    SequenceSpec("income_statement", ("gross profit", "operating expenses"), 23),
    SequenceSpec("income_statement", ("gross profit", "interest expense"), 22),
    SequenceSpec(
        "income_statement", ("operating expenses", "loss from operations"), 22
    ),
    SequenceSpec(
        "income_statement",
        (
            "operating expenses",
            "general and administrative",
            "total operating expenses",
        ),
        31,
    ),
    SequenceSpec(
        "income_statement",
        ("operating expenses", "research and development", "total operating expenses"),
        25,
    ),
    SequenceSpec(
        "income_statement",
        (
            "operating expenses",
            "research and development",
            "general and administrative",
        ),
        21,
    ),
    SequenceSpec(
        "income_statement",
        (
            "research and development",
            "general and administrative",
            "total operating expenses",
        ),
        20,
    ),
    SequenceSpec(
        "income_statement",
        ("operating expenses", "total operating expenses", "net loss"),
        19,
    ),
    SequenceSpec(
        "income_statement",
        ("operating expenses", "general and administrative", "net loss"),
        18,
    ),
    SequenceSpec(
        "income_statement",
        ("research and development", "general and administrative", "net loss"),
        18,
    ),
    SequenceSpec(
        "income_statement",
        ("operating expenses", "general and administrative", "loss from operations"),
        17,
    ),
    SequenceSpec(
        "income_statement",
        ("operating expenses", "loss from operations", "net loss"),
        17,
    ),
    SequenceSpec(
        "income_statement",
        ("general and administrative", "total operating expenses", "net loss"),
        17,
    ),
    SequenceSpec("balance_sheet", ("total assets", "total liabilities"), 91),
    SequenceSpec("balance_sheet", ("assets", "total assets"), 90),
    SequenceSpec("balance_sheet", ("assets", "total liabilities"), 80),
    SequenceSpec("balance_sheet", ("total current assets", "total assets"), 68),
    SequenceSpec("balance_sheet", ("current assets", "total assets"), 67),
    SequenceSpec("balance_sheet", ("assets", "total current assets"), 65),
    SequenceSpec("balance_sheet", ("total assets", "current liabilities"), 64),
    SequenceSpec("balance_sheet", ("assets", "current assets"), 63),
    SequenceSpec("balance_sheet", ("cash and cash equivalents", "total assets"), 63),
    SequenceSpec(
        "balance_sheet", ("total current assets", "total current liabilities"), 63
    ),
    SequenceSpec("balance_sheet", ("current assets", "current liabilities"), 63),
    SequenceSpec("balance_sheet", ("total assets", "total current liabilities"), 62),
    SequenceSpec("balance_sheet", ("current assets", "total current assets"), 61),
    SequenceSpec("balance_sheet", ("assets", "current liabilities"), 60),
    SequenceSpec("balance_sheet", ("assets", "cash and cash equivalents"), 59),
    SequenceSpec("balance_sheet", ("assets", "total assets", "total liabilities"), 80),
    SequenceSpec(
        "balance_sheet", ("assets", "total current assets", "total assets"), 64
    ),
    SequenceSpec("balance_sheet", ("assets", "current assets", "total assets"), 62),
    SequenceSpec(
        "balance_sheet",
        ("total current assets", "total assets", "total current liabilities"),
        62,
    ),
    SequenceSpec(
        "balance_sheet", ("current assets", "total assets", "current liabilities"), 62
    ),
    SequenceSpec(
        "balance_sheet", ("current assets", "total current assets", "total assets"), 61
    ),
    SequenceSpec(
        "balance_sheet", ("assets", "current assets", "total current assets"), 60
    ),
    SequenceSpec(
        "balance_sheet",
        ("assets", "total current assets", "total current liabilities"),
        59,
    ),
    SequenceSpec(
        "balance_sheet", ("assets", "current assets", "current liabilities"), 59
    ),
    SequenceSpec(
        "balance_sheet", ("assets", "total assets", "current liabilities"), 59
    ),
    SequenceSpec(
        "cash_flow",
        (
            "cash flows from investing activities",
            "cash flows from financing activities",
        ),
        64,
    ),
    SequenceSpec(
        "cash_flow",
        (
            "cash flows from operating activities",
            "cash flows from financing activities",
        ),
        63,
    ),
    SequenceSpec(
        "cash_flow",
        (
            "cash flows from operating activities",
            "cash flows from investing activities",
        ),
        61,
    ),
    SequenceSpec(
        "cash_flow",
        (
            "net cash used in investing activities",
            "cash flows from financing activities",
        ),
        39,
    ),
    SequenceSpec(
        "cash_flow",
        (
            "cash flows from investing activities",
            "net cash used in investing activities",
        ),
        38,
    ),
    SequenceSpec("cash_flow", ("operating activities", "investing activities"), 36),
    SequenceSpec(
        "cash_flow",
        (
            "changes in operating assets and liabilities",
            "cash flows from financing activities",
        ),
        36,
    ),
    SequenceSpec("cash_flow", ("investing activities", "financing activities"), 35),
    SequenceSpec(
        "cash_flow",
        (
            "cash flows from operating activities",
            "changes in operating assets and liabilities",
        ),
        35,
    ),
    SequenceSpec("cash_flow", ("operating activities", "financing activities"), 34),
    SequenceSpec(
        "cash_flow",
        ("depreciation and amortization", "cash flows from investing activities"),
        34,
    ),
    SequenceSpec(
        "cash_flow",
        ("depreciation and amortization", "cash flows from financing activities"),
        34,
    ),
    SequenceSpec(
        "cash_flow",
        (
            "changes in operating assets and liabilities",
            "cash flows from investing activities",
        ),
        34,
    ),
    SequenceSpec(
        "cash_flow",
        ("cash flows from operating activities", "depreciation and amortization"),
        34,
    ),
    SequenceSpec(
        "cash_flow",
        (
            "net cash used in investing activities",
            "net cash provided by financing activities",
        ),
        33,
    ),
    SequenceSpec(
        "cash_flow",
        (
            "cash flows from operating activities",
            "cash flows from investing activities",
            "cash flows from financing activities",
        ),
        56,
    ),
    SequenceSpec(
        "cash_flow",
        (
            "cash flows from investing activities",
            "net cash used in investing activities",
            "cash flows from financing activities",
        ),
        37,
    ),
    SequenceSpec(
        "cash_flow",
        ("operating activities", "investing activities", "financing activities"),
        33,
    ),
    SequenceSpec(
        "cash_flow",
        (
            "depreciation and amortization",
            "cash flows from investing activities",
            "cash flows from financing activities",
        ),
        33,
    ),
    SequenceSpec(
        "cash_flow",
        (
            "cash flows from operating activities",
            "changes in operating assets and liabilities",
            "cash flows from financing activities",
        ),
        33,
    ),
    SequenceSpec(
        "cash_flow",
        (
            "changes in operating assets and liabilities",
            "cash flows from investing activities",
            "cash flows from financing activities",
        ),
        33,
    ),
    SequenceSpec(
        "cash_flow",
        (
            "cash flows from operating activities",
            "depreciation and amortization",
            "cash flows from investing activities",
        ),
        33,
    ),
    SequenceSpec(
        "cash_flow",
        (
            "cash flows from operating activities",
            "depreciation and amortization",
            "cash flows from financing activities",
        ),
        33,
    ),
    SequenceSpec(
        "cash_flow",
        (
            "cash flows from operating activities",
            "cash flows from investing activities",
            "net cash used in investing activities",
        ),
        32,
    ),
    SequenceSpec(
        "cash_flow",
        (
            "cash flows from operating activities",
            "net cash used in investing activities",
            "cash flows from financing activities",
        ),
        32,
    ),
    SequenceSpec(
        "stock_comp_rollforward",
        ("granted", "exercised"),
        6,
        PROV_COVERAGE_DISCOVERY,
    ),
    SequenceSpec(
        "aoci",
        ("balance at beginning of period", "balance at end of period"),
        3,
        PROV_COVERAGE_DISCOVERY,
    ),
    SequenceSpec(
        "aoci",
        ("beginning balance", "ending balance"),
        3,
        PROV_COVERAGE_DISCOVERY,
    ),
)


@dataclass(frozen=True, slots=True)
class IdentitySpec:
    """One measured registry entry; provenance names its source."""

    family: str
    name: str
    tier: str
    coverage: float
    closure: float
    points: float
    provenance: str = PROV_MATH
    points_provenance: str = PROV_MATH_POINTS


# Points are priced like label evidence (1 + 3 x exclusivity), the
# exclusivity measured on firing over labelled closed firings.
IDENTITIES: tuple[IdentitySpec, ...] = (
    IdentitySpec(
        "balance_sheet", "balance_sheet_either_form", "standard", 0.735, 0.977, 2.39
    ),
    IdentitySpec("cash_flow", "cash_flow_with_fx_leg", "standard", 0.430, 0.985, 2.73),
    IdentitySpec("income_statement", "gross_profit_leg1", "weak", 0.247, 0.895, 2.11),
)
IDENTITIES_BY_FAMILY = {spec.family: spec for spec in IDENTITIES}

FLAVORS: tuple[FlavorSpec, ...] = (
    FlavorSpec("balance_sheet", "classified", 73, 68, True),
    FlavorSpec("balance_sheet", "unclassified", 44, 34, True),
    FlavorSpec("income_statement", "multi_step", 55, 29, True),
    FlavorSpec("income_statement", "single_step", 99, 53, True),
    FlavorSpec("cash_flow", "indirect", 103, 94, True),
    FlavorSpec("cash_flow", "direct", 0, 0, False),
)


@dataclass(frozen=True, slots=True)
class ContainmentSpec:
    """A measured containment edge: subset sections inside a parent."""

    subset: str
    parent: str
    carriers: int
    parent_support: int
    baseline_rate: float
    lift: float
    provenance: str = PROV_CONTAINMENT


# Only edges the containment census measured out carry standing: aoci
# sections inside equity statements (4 of 9 labelled parents, lift 66x);
# stock_comp and shares_purchased into equity measured 0 of 9 — absent.
CONTAINMENT_EDGES: tuple[ContainmentSpec, ...] = (
    ContainmentSpec("aoci", "equity_statement", 4, 9, 0.007, 66.1),
)
CONTAINMENT_PARENTS = {spec.subset: spec.parent for spec in CONTAINMENT_EDGES}
CONTAINMENT_SUBSETS: dict[str, tuple[str, ...]] = {}
for _spec in CONTAINMENT_EDGES:
    CONTAINMENT_SUBSETS[_spec.parent] = (
        *CONTAINMENT_SUBSETS.get(_spec.parent, ()),
        _spec.subset,
    )


@dataclass(frozen=True, slots=True)
class CoNoteSpec:
    """Families measured as co-note siblings, not containment."""

    families: tuple[str, str]
    colocation: tuple[float, float]
    provenance: str = PROV_CONTAINMENT


# Signature tests failed both directions for the tax pair; note
# colocation is decisive (0.50 of deferred_tax members share a note key
# with a tax_reconciliation geometry, 0.857 in reverse).
CO_NOTE_SIBLINGS: tuple[CoNoteSpec, ...] = (
    CoNoteSpec(("deferred_tax", "tax_reconciliation"), (0.50, 0.857)),
)
