"""Retained negative evidence: measured cross-family veto terms."""

from __future__ import annotations

from edgar_sec.engine.tables.extraction.registry import (
    PROV_REPAIR_NEGATIVE,
    NegativeSpec,
)

_REPAIR_ROWS: tuple[tuple[str, str, float], ...] = (
    ("balance_sheet", "investment securities", 0.008547),
    ("balance_sheet", "non-controlling interest", 0.008547),
    ("balance_sheet", "non-current assets", 0.008547),
    ("balance_sheet", "non-current liabilities", 0.008547),
    ("balance_sheet", "total interest-bearing liabilities", 0.0),
    ("balance_sheet", "total interest-earning assets", 0.0),
    ("balance_sheet", "assets held for sale", 0.017094),
    ("balance_sheet", "net interest income", 0.0),
    ("balance_sheet", "noncontrolling interests", 0.017094),
    ("balance_sheet", "property and equipment", 0.0),
    ("balance_sheet", "accrued interest", 0.017094),
    ("balance_sheet", "income taxes receivable", 0.017094),
    ("balance_sheet", "interest-earning assets", 0.0),
    ("balance_sheet", "money market funds", 0.008547),
    ("balance_sheet", "other accrued expenses", 0.017094),
    ("balance_sheet", "other intangible assets, net", 0.008547),
    ("balance_sheet", "accrued expenses and other", 0.0),
    ("balance_sheet", "debt", 0.008547),
    ("balance_sheet", "deferred tax liability", 0.017094),
    ("balance_sheet", "interest-bearing liabilities", 0.0),
    ("balance_sheet", "net assets acquired", 0.008547),
    ("balance_sheet", "net income", 0.0),
    ("balance_sheet", "other accrued liabilities", 0.017094),
    ("balance_sheet", "other noncurrent assets", 0.017094),
    ("balance_sheet", "total cash and cash equivalents", 0.0),
    ("balance_sheet", "total interest-bearing deposits", 0.0),
    ("cash_flow", "repurchases of common stock", 0.019868),
    ("cash_flow", "cash and cash equivalents at end of year", 0.019868),
    ("cash_flow", "amortization of deferred financing costs", 0.006623),
    ("cash_flow", "cash and cash equivalents, beginning of year", 0.019868),
    ("cash_flow", "cash and cash equivalents, end of year", 0.006623),
    ("cash_flow", "other financing activities", 0.013245),
    ("cash_flow", "increase (decrease) in cash and cash equivalents", 0.019868),
    ("cash_flow", "purchases", 0.013245),
    ("cash_flow", "amortization of above-market lease", 0.0),
    ("cash_flow", "amortization of debt discount", 0.019868),
    ("cash_flow", "cash provided by operating activities", 0.006623),
    ("cash_flow", "cash used in investing activities", 0.006623),
    ("cash_flow", "deferred income tax benefit", 0.0),
    ("cash_flow", "effect of foreign currency translation on cash", 0.0),
    ("cash_flow", "issuance of common stock", 0.013245),
    ("cash_flow", "payments for business acquisitions, net of cash acquired", 0.0),
    ("cash_flow", "repayments of long-term debt", 0.006623),
    ("income_statement", "acquisition and integration expenses", 0.0),
    ("income_statement", "equity in earnings of joint ventures", 0.0),
    ("income_statement", "management fees", 0.012987),
    ("income_statement", "net loss attributable to common stockholders", 0.0),
    (
        "income_statement",
        "noncontrolling interests in income of consolidated subsidiaries, net of tax",
        0.0,
    ),
    ("income_statement", "professional services and other", 0.0),
    ("income_statement", "subscription and support", 0.0),
    ("income_statement", "net (loss) income", 0.019481),
    ("income_statement", "(loss) income before income taxes", 0.006494),
    ("income_statement", "income before income tax expense", 0.019481),
    ("income_statement", "loss before provision for income taxes", 0.006494),
    ("income_statement", "selling and marketing", 0.012987),
    ("income_statement", "total other expense", 0.012987),
    ("income_statement", "advertising", 0.006494),
    ("income_statement", "costs of goods sold, buying and occupancy", 0.0),
    ("income_statement", "employee related expenses", 0.0),
    ("income_statement", "general, administrative and store operating expenses", 0.0),
    ("income_statement", "income before provision for income taxes", 0.0),
    ("income_statement", "net revenue", 0.019481),
    ("income_statement", "repair and maintenance", 0.0),
    ("income_statement", "total stock-based compensation expense", 0.0),
    ("aoci", "recoveries", 0.0),
    ("aoci", "charge-offs", 0.0),
    ("aoci", "provision for credit losses", 0.0),
    ("aoci", "changes in fair value, net", 0.0),
)


NEGATIVE_EVIDENCE: tuple[NegativeSpec, ...] = (
    NegativeSpec("balance_sheet", "accumulated deficit", "aoci", 0.0),
    NegativeSpec("balance_sheet", "stockholders’ equity", "aoci", 0.0),
    NegativeSpec("balance_sheet", "total stockholders’ equity", "aoci", 0.0),
    NegativeSpec("balance_sheet", "liabilities and stockholders’ equity", "aoci", 0.0),
    NegativeSpec(
        "balance_sheet", "total liabilities and stockholders’ equity", "aoci", 0.0
    ),
    NegativeSpec("balance_sheet", "commitments and contingencies", "aoci", 0.0),
    NegativeSpec(
        "balance_sheet", "accumulated other comprehensive income (loss)", "aoci", 0.0
    ),
    NegativeSpec("balance_sheet", "accumulated deficit", "cash_flow", 0.0),
    NegativeSpec("balance_sheet", "stockholders’ equity", "cash_flow", 0.0),
    NegativeSpec("balance_sheet", "total stockholders’ equity", "cash_flow", 0.0),
    NegativeSpec(
        "balance_sheet", "liabilities and stockholders’ equity", "cash_flow", 0.0
    ),
    NegativeSpec(
        "balance_sheet", "total liabilities and stockholders’ equity", "cash_flow", 0.0
    ),
    NegativeSpec("balance_sheet", "commitments and contingencies", "cash_flow", 0.0),
    NegativeSpec(
        "balance_sheet",
        "accumulated other comprehensive income (loss)",
        "cash_flow",
        0.0,
    ),
    NegativeSpec("balance_sheet", "accumulated deficit", "cover_layout", 0.0),
    NegativeSpec("balance_sheet", "stockholders’ equity", "cover_layout", 0.0),
    NegativeSpec("balance_sheet", "total stockholders’ equity", "cover_layout", 0.0),
    NegativeSpec(
        "balance_sheet", "liabilities and stockholders’ equity", "cover_layout", 0.0
    ),
    NegativeSpec(
        "balance_sheet",
        "total liabilities and stockholders’ equity",
        "cover_layout",
        0.0,
    ),
    NegativeSpec("balance_sheet", "commitments and contingencies", "cover_layout", 0.0),
    NegativeSpec(
        "balance_sheet",
        "accumulated other comprehensive income (loss)",
        "cover_layout",
        0.0,
    ),
    NegativeSpec("balance_sheet", "accumulated deficit", "debt_maturity", 0.0),
    NegativeSpec("balance_sheet", "stockholders’ equity", "debt_maturity", 0.0),
    NegativeSpec("balance_sheet", "total stockholders’ equity", "debt_maturity", 0.0),
    NegativeSpec(
        "balance_sheet", "liabilities and stockholders’ equity", "debt_maturity", 0.0
    ),
    NegativeSpec(
        "balance_sheet",
        "total liabilities and stockholders’ equity",
        "debt_maturity",
        0.0,
    ),
    NegativeSpec(
        "balance_sheet", "commitments and contingencies", "debt_maturity", 0.0
    ),
    NegativeSpec(
        "balance_sheet",
        "accumulated other comprehensive income (loss)",
        "debt_maturity",
        0.0,
    ),
    NegativeSpec("balance_sheet", "accumulated deficit", "deferred_tax", 0.0),
    NegativeSpec("balance_sheet", "stockholders’ equity", "deferred_tax", 0.0),
    NegativeSpec("balance_sheet", "total stockholders’ equity", "deferred_tax", 0.0),
    NegativeSpec(
        "balance_sheet", "liabilities and stockholders’ equity", "deferred_tax", 0.0
    ),
    NegativeSpec(
        "balance_sheet",
        "total liabilities and stockholders’ equity",
        "deferred_tax",
        0.0,
    ),
    NegativeSpec("balance_sheet", "commitments and contingencies", "deferred_tax", 0.0),
    NegativeSpec(
        "balance_sheet",
        "accumulated other comprehensive income (loss)",
        "deferred_tax",
        0.0,
    ),
    NegativeSpec("balance_sheet", "accumulated deficit", "derivatives_hedging", 0.0),
    NegativeSpec("balance_sheet", "stockholders’ equity", "derivatives_hedging", 0.0),
    NegativeSpec(
        "balance_sheet", "total stockholders’ equity", "derivatives_hedging", 0.0
    ),
    NegativeSpec(
        "balance_sheet",
        "liabilities and stockholders’ equity",
        "derivatives_hedging",
        0.0,
    ),
    NegativeSpec(
        "balance_sheet",
        "total liabilities and stockholders’ equity",
        "derivatives_hedging",
        0.0,
    ),
    NegativeSpec("cash_flow", "investing activities", "aoci", 0.0),
    NegativeSpec("cash_flow", "cash flows from financing activities", "aoci", 0.0),
    NegativeSpec("cash_flow", "cash flows from operating activities", "aoci", 0.0),
    NegativeSpec("cash_flow", "cash flows from investing activities", "aoci", 0.0),
    NegativeSpec("cash_flow", "net increase", "aoci", 0.0),
    NegativeSpec("cash_flow", "net cash used in investing activities", "aoci", 0.0),
    NegativeSpec("cash_flow", "net cash provided by financing activities", "aoci", 0.0),
    NegativeSpec(
        "cash_flow", "changes in operating assets and liabilities", "aoci", 0.0
    ),
    NegativeSpec("cash_flow", "net cash used in operating activities", "aoci", 0.0),
    NegativeSpec("cash_flow", "repayment", "aoci", 0.0),
    NegativeSpec(
        "cash_flow", "cash and cash equivalents at end of period", "aoci", 0.0
    ),
    NegativeSpec(
        "cash_flow", "net cash provided by (used in) operating activities", "aoci", 0.0
    ),
    NegativeSpec(
        "cash_flow", "net cash provided by (used in) financing activities", "aoci", 0.0
    ),
    NegativeSpec(
        "cash_flow", "cash and cash equivalents at beginning of period", "aoci", 0.0
    ),
    NegativeSpec(
        "cash_flow", "net increase (decrease) in cash and cash equivalents", "aoci", 0.0
    ),
    NegativeSpec("cash_flow", "supplemental disclosures", "aoci", 0.0),
    NegativeSpec("cash_flow", "principal payments", "aoci", 0.0),
    NegativeSpec(
        "cash_flow", "supplemental disclosures of cash flow information", "aoci", 0.0
    ),
    NegativeSpec(
        "cash_flow",
        "effect of exchange rate changes on cash and cash equivalents",
        "aoci",
        0.0,
    ),
    NegativeSpec("cash_flow", "effect of exchange rate changes on cash", "aoci", 0.0),
    NegativeSpec("cash_flow", "proceeds from issuance of common stock", "aoci", 0.0),
    NegativeSpec("cash_flow", "net change in cash", "aoci", 0.0),
    NegativeSpec("cash_flow", "net cash provided by investing activities", "aoci", 0.0),
    NegativeSpec("cash_flow", "cash at end of period", "aoci", 0.0),
    NegativeSpec("cash_flow", "net increase (decrease) in cash", "aoci", 0.0),
    NegativeSpec("cash_flow", "investing activities", "balance_sheet", 0.0),
    NegativeSpec(
        "cash_flow", "cash flows from financing activities", "balance_sheet", 0.0
    ),
    NegativeSpec(
        "cash_flow", "cash flows from operating activities", "balance_sheet", 0.0
    ),
    NegativeSpec(
        "cash_flow", "cash flows from investing activities", "balance_sheet", 0.0
    ),
    NegativeSpec("cash_flow", "net increase", "balance_sheet", 0.0),
    NegativeSpec(
        "cash_flow", "net cash used in investing activities", "balance_sheet", 0.0
    ),
    NegativeSpec(
        "cash_flow", "net cash provided by financing activities", "balance_sheet", 0.0
    ),
    NegativeSpec(
        "cash_flow", "changes in operating assets and liabilities", "balance_sheet", 0.0
    ),
    NegativeSpec(
        "cash_flow", "net cash used in operating activities", "balance_sheet", 0.0
    ),
    NegativeSpec("cash_flow", "repayment", "balance_sheet", 0.0),
    NegativeSpec(
        "cash_flow", "cash and cash equivalents at end of period", "balance_sheet", 0.0
    ),
    NegativeSpec(
        "cash_flow",
        "net cash provided by (used in) operating activities",
        "balance_sheet",
        0.0,
    ),
    NegativeSpec(
        "cash_flow",
        "net cash provided by (used in) financing activities",
        "balance_sheet",
        0.0,
    ),
    NegativeSpec(
        "cash_flow",
        "cash and cash equivalents at beginning of period",
        "balance_sheet",
        0.0,
    ),
    NegativeSpec(
        "cash_flow",
        "net increase (decrease) in cash and cash equivalents",
        "balance_sheet",
        0.0,
    ),
    NegativeSpec("income_statement", "collaboration revenue", "aoci", 0.0),
    NegativeSpec("income_statement", "other (income) expense", "aoci", 0.0),
    NegativeSpec(
        "income_statement",
        "cost of services (exclusive of depreciation and amortization)",
        "aoci",
        0.0,
    ),
    NegativeSpec("income_statement", "collaboration revenue", "balance_sheet", 0.0),
    NegativeSpec("income_statement", "other (income) expense", "balance_sheet", 0.0),
    NegativeSpec(
        "income_statement",
        "cost of services (exclusive of depreciation and amortization)",
        "balance_sheet",
        0.0,
    ),
    NegativeSpec("income_statement", "collaboration revenue", "cash_flow", 0.0),
    NegativeSpec("income_statement", "other (income) expense", "cash_flow", 0.0),
    NegativeSpec(
        "income_statement",
        "cost of services (exclusive of depreciation and amortization)",
        "cash_flow",
        0.0,
    ),
    NegativeSpec("income_statement", "collaboration revenue", "cover_layout", 0.0),
    NegativeSpec("income_statement", "other (income) expense", "cover_layout", 0.0),
    NegativeSpec(
        "income_statement",
        "cost of services (exclusive of depreciation and amortization)",
        "cover_layout",
        0.0,
    ),
    NegativeSpec("income_statement", "collaboration revenue", "debt_maturity", 0.0),
    NegativeSpec("income_statement", "other (income) expense", "debt_maturity", 0.0),
    NegativeSpec(
        "income_statement",
        "cost of services (exclusive of depreciation and amortization)",
        "debt_maturity",
        0.0,
    ),
    NegativeSpec("income_statement", "collaboration revenue", "deferred_tax", 0.0),
    NegativeSpec("income_statement", "other (income) expense", "deferred_tax", 0.0),
    NegativeSpec(
        "income_statement",
        "cost of services (exclusive of depreciation and amortization)",
        "deferred_tax",
        0.0,
    ),
    NegativeSpec(
        "income_statement", "collaboration revenue", "derivatives_hedging", 0.0
    ),
    NegativeSpec(
        "income_statement", "other (income) expense", "derivatives_hedging", 0.0
    ),
    NegativeSpec(
        "income_statement",
        "cost of services (exclusive of depreciation and amortization)",
        "derivatives_hedging",
        0.0,
    ),
    NegativeSpec(
        "income_statement", "collaboration revenue", "eps_reconciliation", 0.0
    ),
    NegativeSpec(
        "income_statement", "other (income) expense", "eps_reconciliation", 0.0
    ),
    NegativeSpec(
        "income_statement",
        "cost of services (exclusive of depreciation and amortization)",
        "eps_reconciliation",
        0.0,
    ),
    NegativeSpec("income_statement", "collaboration revenue", "equity_statement", 0.0),
    NegativeSpec("income_statement", "other (income) expense", "equity_statement", 0.0),
    NegativeSpec(
        "income_statement",
        "cost of services (exclusive of depreciation and amortization)",
        "equity_statement",
        0.0,
    ),
    NegativeSpec("income_statement", "collaboration revenue", "fair_value", 0.0),
    NegativeSpec("income_statement", "other (income) expense", "fair_value", 0.0),
    NegativeSpec(
        "income_statement",
        "cost of services (exclusive of depreciation and amortization)",
        "fair_value",
        0.0,
    ),
    NegativeSpec("income_statement", "collaboration revenue", "intangibles", 0.0),
    NegativeSpec("income_statement", "other (income) expense", "intangibles", 0.0),
    NegativeSpec(
        "income_statement",
        "cost of services (exclusive of depreciation and amortization)",
        "intangibles",
        0.0,
    ),
    NegativeSpec("income_statement", "collaboration revenue", "inventory", 0.0),
    NegativeSpec("income_statement", "other (income) expense", "inventory", 0.0),
    NegativeSpec(
        "income_statement",
        "cost of services (exclusive of depreciation and amortization)",
        "inventory",
        0.0,
    ),
    NegativeSpec("income_statement", "collaboration revenue", "lease_maturity", 0.0),
    NegativeSpec("income_statement", "other (income) expense", "lease_maturity", 0.0),
    NegativeSpec(
        "income_statement",
        "cost of services (exclusive of depreciation and amortization)",
        "lease_maturity",
        0.0,
    ),
    NegativeSpec("income_statement", "collaboration revenue", "other", 0.0),
    NegativeSpec("lease_maturity", "less: imputed interest", "aoci", 0.0),
    NegativeSpec("lease_maturity", "less: imputed interest", "balance_sheet", 0.0),
    NegativeSpec("lease_maturity", "less: imputed interest", "cash_flow", 0.0),
    NegativeSpec("lease_maturity", "less: imputed interest", "cover_layout", 0.0),
    NegativeSpec("lease_maturity", "less: imputed interest", "deferred_tax", 0.0),
    NegativeSpec(
        "lease_maturity", "less: imputed interest", "derivatives_hedging", 0.0
    ),
    NegativeSpec("lease_maturity", "less: imputed interest", "eps_reconciliation", 0.0),
    NegativeSpec("lease_maturity", "less: imputed interest", "equity_statement", 0.0),
    NegativeSpec("lease_maturity", "less: imputed interest", "fair_value", 0.0),
    NegativeSpec("lease_maturity", "less: imputed interest", "income_statement", 0.0),
    NegativeSpec("lease_maturity", "less: imputed interest", "intangibles", 0.0),
    NegativeSpec("lease_maturity", "less: imputed interest", "inventory", 0.0),
    NegativeSpec("lease_maturity", "less: imputed interest", "pension", 0.0),
    NegativeSpec("lease_maturity", "less: imputed interest", "ppe", 0.0),
    NegativeSpec("lease_maturity", "less: imputed interest", "shares_purchased", 0.0),
    NegativeSpec(
        "lease_maturity", "less: imputed interest", "stock_comp_rollforward", 0.0
    ),
    NegativeSpec("lease_maturity", "less: imputed interest", "tax_reconciliation", 0.0),
    NegativeSpec("lease_maturity", "less: imputed interest", "other", 0.0005),
    NegativeSpec("other", "total", "aoci", 0.0),
    NegativeSpec("other", "and", "aoci", 0.0),
    NegativeSpec("other", "other", "aoci", 0.0),
    NegativeSpec("other", "net", "aoci", 0.0),
    NegativeSpec("other", "income", "aoci", 0.0),
    NegativeSpec("other", "interest", "aoci", 0.0),
    NegativeSpec("other", "assets", "aoci", 0.0),
    NegativeSpec("other", "loss", "aoci", 0.0),
    NegativeSpec("other", "cash", "aoci", 0.0),
    NegativeSpec("other", "operating", "aoci", 0.0),
    NegativeSpec("other", "liabilities", "aoci", 0.0),
    NegativeSpec("other", "expense", "aoci", 0.0),
    NegativeSpec("other", "expenses", "aoci", 0.0),
    NegativeSpec("other", "common", "aoci", 0.0),
    NegativeSpec("other", "equity", "aoci", 0.0),
    NegativeSpec("other", "securities", "aoci", 0.0),
    NegativeSpec("other", "loans", "aoci", 0.0),
    NegativeSpec("other", "debt", "aoci", 0.0),
    NegativeSpec("other", "december", "aoci", 0.0),
    NegativeSpec("other", "revenue", "aoci", 0.0),
    NegativeSpec("other", "taxes", "aoci", 0.0),
    NegativeSpec("other", "net income", "aoci", 0.0),
    NegativeSpec("other", "amortization", "aoci", 0.0),
    NegativeSpec("other", "current", "aoci", 0.0),
    NegativeSpec("other", "cost", "aoci", 0.0),
    NegativeSpec("other", "sales", "aoci", 0.0),
    NegativeSpec("other", "equipment", "aoci", 0.0),
    NegativeSpec("other", "rate", "aoci", 0.0),
    NegativeSpec("other", "costs", "aoci", 0.0),
    NegativeSpec("other", "average", "aoci", 0.0),
    NegativeSpec("other", "beginning", "aoci", 0.0),
    NegativeSpec("other", "compensation", "aoci", 0.0),
    NegativeSpec("other", "deferred", "aoci", 0.0),
    NegativeSpec("other", "common stock", "aoci", 0.0),
    NegativeSpec("other", "depreciation", "aoci", 0.0),
    NegativeSpec("other", "outstanding", "aoci", 0.0),
    NegativeSpec("other", "income taxes", "aoci", 0.0),
    NegativeSpec("other", "credit", "aoci", 0.0),
    NegativeSpec("other", "less", "aoci", 0.0),
    NegativeSpec("other", "period", "aoci", 0.0),
    *(
        NegativeSpec(family, term, family, rate, PROV_REPAIR_NEGATIVE)
        for family, term, rate in _REPAIR_ROWS
    ),
)
