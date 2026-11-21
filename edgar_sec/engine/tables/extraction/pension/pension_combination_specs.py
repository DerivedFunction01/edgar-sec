"""Pension combination separator: priced leg data as spec constants.

The FULL composition's claim-local legs over the census
population: core and revenue term sets, the half-derived host
stub-key vocabularies, and the commitments header/token sets.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PensionCombinationSpec:
    """The combination separator's priced thresholds."""

    rows_max: int = 2
    hdr_min_hits: int = 2
    real_table_min_rows: int = 3
    real_table_min_cols: int = 4


PENSION_COMBINATION_SPEC = PensionCombinationSpec()

COMBINATION_CORE_TERMS = frozenset(
    {
        "service cost",
        "interest cost",
        "expected return",
        "net periodic",
        "funded status",
        "benefit obligation",
        "plan assets",
        "actuarial",
        "amortization",
        "settlement",
        "curtailment",
        "benefit payments",
        "defined benefit",
    }
)

REVENUE_STUBS = frozenset(
    {
        "net sales",
        "total revenues",
        "net revenue",
        "revenues",
        "total net sales",
        "sales",
    }
)

GUARANTEE_TOKENS = frozenset({"guarantee", "guarantees"})

CC_TOKEN_VOCAB = frozenset(
    {
        "by",
        "capital",
        "commitments",
        "debt",
        "due",
        "lease",
        "letters",
        "operating",
        "payments",
        "period",
        "purchase",
    }
)

CC_HDR_VOCAB = frozenset(
    {
        "after",
        "due",
        "less",
        "less than",
        "payments",
        "period",
        "than",
        "total",
        "years",
    }
)

HOST_COMBINATION_VOCAB = {
    "aoci_rollforward": frozenset(
        {
            "amounts reclassified from accumulated other comprehensive loss",
            "amounts reclassified from aoci",
            "balance at",
            "beginning balance",
            "ending balance",
            "net current period other comprehensive income loss",
            "other comprehensive loss",
            "other comprehensive loss before reclassifications",
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
            "accrued expenses",
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
            "inventories",
            "liabilities and stockholders equity",
            "long term debt",
            "other assets",
            "other current assets",
            "other long term liabilities",
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
            "deferred income taxes",
            "depreciation and amortization",
            "financing activities",
            "inventories",
            "net cash provided by financing activities",
            "net cash provided by operating activities",
            "net cash used in investing activities",
            "net income",
            "operating activities",
        }
    ),
    "commitments_contingencies": frozenset({"year", "years"}),
    "comprehensive_income": frozenset(
        {
            "comprehensive income",
            "net income",
            "other comprehensive income loss net of tax",
            "total other comprehensive income loss",
        }
    ),
    "credit_losses_rollforward": frozenset(
        {
            "allowance for credit losses",
            "allowance for loan losses",
            "beginning balance",
            "charge offs",
            "ending balance",
            "recoveries",
        }
    ),
    "debt_maturity": frozenset({"thereafter"}),
    "deferred_tax": frozenset(
        {
            "accrued expenses",
            "deferred tax assets",
            "deferred tax liabilities",
            "intangibles",
            "less valuation allowance",
            "net deferred tax asset",
            "other",
            "total deferred tax assets",
            "total deferred tax liabilities",
            "valuation allowance",
        }
    ),
    "eps_reconciliation": frozenset(
        {
            "basic",
            "denominator",
            "diluted",
            "effect of dilutive securities",
            "net income",
            "numerator",
        }
    ),
    "equity_statement": frozenset(
        {
            "balance at",
            "net income",
            "net loss",
            "other comprehensive income",
            "other comprehensive loss",
            "stock based compensation",
        }
    ),
    "fair_value": frozenset({"assets"}),
    "goodwill": frozenset({"balance as of", "goodwill"}),
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
            "research and development",
            "revenue",
            "revenues",
            "total operating expenses",
        }
    ),
    "intangibles": frozenset({"customer relationships"}),
    "inventory": frozenset({"finished goods", "raw materials", "work in process"}),
    "lease_maturity": frozenset(
        {
            "less imputed interest",
            "present value of lease liabilities",
            "thereafter",
            "total lease payments",
        }
    ),
    "ppe": frozenset(
        {"land", "leasehold improvements", "less accumulated depreciation"}
    ),
    "restructuring": frozenset({"balance at", "cash payments"}),
    "shares_purchased": frozenset({"issuer purchases of equity securities", "period"}),
    "stock_comp_rollforward": frozenset(
        {"exercised", "forfeited", "granted", "vested"}
    ),
    "valuation_model_assumptions": frozenset(
        {
            "dividend yield",
            "expected dividend yield",
            "expected volatility",
            "risk free interest rate",
        }
    ),
}
