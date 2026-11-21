"""Pension routed separator parameters (TEST_PENSION_ROUTED).

The priced routed form as data: sub-kind marker stems, per-kind
kill cells, increment terms, and the frozen census supporting
vocabularies (provenance: PROV_PENSION_ROUTED).
"""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.foundation.text.dates import MONTH_ALIASES, MONTH_NAMES

KIND_ORDER = ("cost", "walk", "funded", "assumptions", "assets", "payments")

MARKER_STEMS = {
    "cost": (
        "service cost",
        "interest cost",
        "expected return",
        "net periodic",
        "amortization of prior service",
        "amortization of net",
        "amortization of actuarial",
        "net amortization",
        "recognized actuarial",
        "recognized net",
        "recognized prior service",
        "settlement",
        "curtailment",
        "components of net periodic",
        "total pension expense",
        "total postretirement benefit expense",
    ),
    "walk": (
        "change in benefit obligation",
        "change in projected benefit obligation",
        "change in plan assets",
        "change in fair value of plan assets",
        "benefit obligation at beginning",
        "benefit obligation at end",
        "projected benefit obligation beginning",
        "projected benefit obligation end",
        "fair value of plan assets at beginning",
        "fair value of plan assets at end",
        "fair value of assets at beginning",
        "fair value of assets at end",
        "balance at beginning of period",
        "balance at end of period",
        "actual return on plan assets",
        "benefits paid",
        "benefits and expenses paid",
        "accrued benefit asset liability at beginning",
        "accrued benefit asset liability at end",
    ),
    "funded": (
        "funded status",
        "amounts recognized",
        "accumulated other comprehensive",
        "other comprehensive income",
        "other comprehensive loss",
        "accumulated benefit obligation",
        "underfunded",
        "unfunded",
        "reconciliation of funded status",
        "balance sheet classification",
        "unrecognized net",
        "unrecognized losses",
        "net amount recognized",
        "projected benefit obligation",
    ),
    "assumptions": (
        "discount rate",
        "compensation increase",
        "salary increase",
        "salary progression",
        "expected long term return",
        "long term rate of return",
        "cost trend",
        "trend rate",
        "weighted average",
        "effect on total of service",
        "effect on accumulated",
        "effect on post retirement",
        "effect on other postretirement",
        "percentage point increase",
        "percentage point decrease",
        "health care cost trend",
        "medical cost trend",
        "medical trend",
    ),
    "assets": (
        "equity securities",
        "fixed income",
        "debt securities",
        "real estate",
        "asset category",
    ),
    "payments": (
        "benefit payments",
        "estimated future benefit payments",
        "future expected benefit payments",
        "estimated employer contributions",
        "expected contributions",
    ),
}

STRONG_STEMS = frozenset(
    {
        "net periodic",
        "components of net periodic",
        "change in benefit obligation",
        "change in projected benefit obligation",
        "change in plan assets",
        "change in fair value of plan assets",
        "funded status",
        "reconciliation of funded status",
    }
)

# Per-kind kill cells as leg lists: an "A:" leg kills when its
# feature is present, a "B:" leg when it is absent; any leg fires.
CELL_LEGS = {
    "cost": ("A:movedens_le_0.25", "A:rows_le_5"),
    "walk": ("B:bookend_begin",),
    "funded": (
        "A:hdr:three",
        "A:rows_le_3",
        "A:stub:operating lease obligations",
        "A:hdr:millions of dollars",
    ),
    "assumptions": (
        "A:hdr:three",
        "A:stub:operating lease obligations",
        "A:hdr:millions of dollars",
    ),
}

# The assets cell kills below this share of its strong core terms.
ASSETS_CORE_TERMS = ("equity securities", "real estate", "total")
ASSETS_CORE_SHARE = 0.5

BENEFIT_HDR_TERMS = (
    "pension benefits",
    "postretirement benefits",
    "other benefits",
    "retirement benefits",
    "postemployment benefits",
    "defined benefit",
)

DROP_TOKS = frozenset(
    {
        "fiscal",
        "year",
        "years",
        "ending",
        "the",
        "december",
        "31",
        "as",
        "of",
        "at",
        "for",
    }
)

MOVE_WORDS = frozenset(
    {
        "additions",
        "deductions",
        "increases",
        "decreases",
        "amortization",
        "depreciation",
        "payments",
        "proceeds",
        "purchases",
        "sales",
        "transfers",
        "charges",
        "activity",
        "acquisitions",
        "dispositions",
        "contributions",
        "distributions",
        "settlements",
        "forfeitures",
        "exercises",
        "exercised",
        "grants",
        "granted",
        "issued",
        "issuance",
        "redemptions",
        "repurchases",
        "impairment",
        "accretion",
        "changes",
        "change",
        "adjustments",
        "remeasurement",
        "benefits",
        "service",
        "cost",
        "expense",
        "income",
    }
)

HEADER_STOP_TOKENS = frozenset(
    {
        "and",
        "the",
        "for",
        "of",
        "in",
        "on",
        "at",
        "to",
        "a",
        "an",
        "dollars",
        "thousands",
        "millions",
        "billions",
        "unaudited",
        "audited",
        "per",
        "share",
        "shares",
    }
)

MONTH_TOKENS = frozenset(MONTH_NAMES) | frozenset(
    alias.rstrip(".") for group in MONTH_ALIASES for alias in group
)

# Frozen census core vocabularies at share >= 0.2 per family (the
# pension family itself excluded): the host increment's read set.
HOST_SUPP_VOCAB = {
    "aoci_rollforward": frozenset(
        {
            "balance at",
            "beginning balance",
            "ending balance",
            "other comprehensive income loss before reclassifications",
        }
    ),
    "aro_rollforward": frozenset(
        {
            "accretion",
            "accretion expense",
            "liabilities incurred",
            "liabilities settled",
        }
    ),
    "balance_sheet": frozenset(
        {
            "accounts payable",
            "accumulated deficit",
            "accumulated other comprehensive loss",
            "additional paid in capital",
            "assets",
            "cash and cash equivalents",
            "commitments and contingencies",
            "commitments and contingencies note",
            "current assets",
            "current liabilities",
            "deferred income taxes",
            "goodwill",
            "liabilities and stockholders equity",
            "long term debt",
            "other assets",
            "property and equipment net",
            "retained earnings",
            "stockholders equity",
            "total assets",
            "total current assets",
            "total current liabilities",
            "total liabilities",
            "total liabilities and stockholders equity",
            "total stockholders equity",
        }
    ),
    "cash_flow": frozenset(
        {
            "accounts payable",
            "accounts receivable",
            "adjustments to reconcile net income to net cash",
            "cash flows from financing activities",
            "cash flows from investing activities",
            "cash flows from operating activities",
            "changes in operating assets and liabilities",
            "deferred income taxes",
            "depreciation and amortization",
            "net cash provided by financing activities",
            "net cash provided by operating activities",
            "net cash used in investing activities",
            "net income",
        }
    ),
    "combined_operations_ci": frozenset(
        {
            "comprehensive income",
            "general and administrative",
            "income tax expense",
            "interest expense",
            "interest income",
            "loss from operations",
            "net income",
            "net loss",
            "operating expenses",
            "operating income",
            "operating loss",
            "other comprehensive income loss",
            "research and development",
            "revenue",
            "revenues",
            "total operating expenses",
            "total revenues",
        }
    ),
    "commitments_contingencies": frozenset(
        {
            "operating lease obligations",
            "total",
            "year",
        }
    ),
    "comprehensive_income": frozenset(
        {
            "comprehensive income",
            "net income",
        }
    ),
    "credit_losses_rollforward": frozenset(
        {
            "allowance for loan losses",
            "beginning balance",
            "charge offs",
            "ending balance",
            "recoveries",
        }
    ),
    "debt_maturity": frozenset(
        {
            "thereafter",
            "total",
        }
    ),
    "deferred_tax": frozenset(
        {
            "deferred tax assets",
            "deferred tax liabilities",
            "in thousands",
            "less valuation allowance",
            "net deferred tax asset",
            "other",
            "total deferred tax assets",
            "total deferred tax liabilities",
            "valuation allowance",
        }
    ),
    "derivatives_hedging": frozenset(
        {
            "total",
        }
    ),
    "eps_reconciliation": frozenset(
        {
            "denominator",
            "effect of dilutive securities",
            "numerator",
        }
    ),
    "equity_statement": frozenset(
        {
            "balance",
            "balance at",
            "net income",
            "net loss",
            "stock based compensation",
        }
    ),
    "fair_value": frozenset(
        {
            "assets",
        }
    ),
    "goodwill": frozenset(
        {
            "balance as of",
            "goodwill",
        }
    ),
    "income_statement": frozenset(
        {
            "basic",
            "depreciation and amortization",
            "diluted",
            "expenses",
            "general and administrative",
            "gross profit",
            "interest expense",
            "interest income",
            "net income",
            "net loss",
            "operating expenses",
            "provision for income taxes",
            "research and development",
            "revenue",
            "revenues",
            "total operating expenses",
        }
    ),
    "intangibles": frozenset(
        {
            "customer relationships",
            "total",
        }
    ),
    "inventory": frozenset(
        {
            "finished goods",
            "raw materials",
            "total",
            "work in process",
        }
    ),
    "lease_maturity": frozenset(
        {
            "less imputed interest",
            "thereafter",
            "total",
            "total lease payments",
        }
    ),
    "ppe": frozenset(
        {
            "construction in progress",
            "land",
            "leasehold improvements",
            "less accumulated depreciation",
            "machinery and equipment",
        }
    ),
    "related_party": frozenset(
        {
            "total",
        }
    ),
    "restructuring": frozenset(
        {
            "balance at",
            "cash payments",
        }
    ),
    "shares_purchased": frozenset(
        {
            "issuer purchases of equity securities",
            "period",
            "total",
        }
    ),
    "stock_comp_rollforward": frozenset(
        {
            "exercised",
            "forfeited",
            "granted",
            "vested",
        }
    ),
    "tax_reconciliation": frozenset(
        {
            "effective tax rate",
            "other",
        }
    ),
    "valuation_model_assumptions": frozenset(
        {
            "dividend yield",
            "expected dividend yield",
            "expected volatility",
            "risk free interest rate",
        }
    ),
    "warrant_activity": frozenset(
        {
            "average",
            "exercise price",
            "exercised",
            "expired",
            "issued",
            "outstanding at",
            "remaining",
            "warrants",
            "warrants outstanding at",
        }
    ),
}


@dataclass(frozen=True, slots=True)
class PensionRoutedSpec:
    """Scalar parameters of the routed separator form."""

    seg_min_multiplicity: int = 3
    ladder_min_year_stubs: int = 4
    host_min_hits: int = 2
    payments_due_term: str = "payments due"
    payments_due_host: str = "commitments_contingencies"
    item201d_phrase: str = "shares to be issued upon exercise"
    item201d_host: str = "stock_comp_rollforward"


PENSION_ROUTED_SPEC = PensionRoutedSpec()
