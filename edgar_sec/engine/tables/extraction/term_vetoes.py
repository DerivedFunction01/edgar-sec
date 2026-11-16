"""Priced term vetoes: the Step 6 v2 re-priced sets as data.

HARD terms remove a family's claim outright; SCORED terms lower
its score once per claim, however many hit (any-hit). Channels
as priced: lead is caption + prose_before; body is grid text.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from edgar_sec.engine.tables.extraction.normalize import normalize_text

if TYPE_CHECKING:
    from edgar_sec.engine.tables.extraction.competition import GeometryText


@dataclass(frozen=True, slots=True)
class VetoSpec:
    """One family's priced term vetoes for one channel at one tier."""

    family: str
    channel: str
    tier: str
    terms: tuple[str, ...]


# Step 6 v2 re-priced sets (record: 2026-11-16-greenfield-step6-v2-
# measurement-record). Exclusions: aoci and commitments assembly
# rows, furniture-only rows, and every dagger n-gram row.
TERM_VETOES: tuple[VetoSpec, ...] = (
    VetoSpec(
        "balance_sheet",
        "lead",
        "hard",
        (
            "current assets",
            "income tax",
            "borrowings",
            "credit facility",
            "lease",
            "segment",
            "other comprehensive",
            "unregistered sales",
            "use of proceeds",
            "controls and procedures",
            "table of contents",
            "form 10-k",
            "commitments",
            "contingencies",
            "purchase obligation",
            "square feet",
            "issuer purchases",
        ),
    ),
    VetoSpec(
        "balance_sheet",
        "body",
        "hard",
        (
            "cash flow",
            "cash flows",
            "operating activities",
            "investing activities",
            "financing activities",
            "net cash",
            "net income",
            "current assets",
            "level 1",
            "level 2",
            "level 3",
            "unobservable",
            "quoted prices",
            "actuarial",
            "valuation allowance",
            "senior notes",
            "vesting",
            "unregistered sales",
            "use of proceeds",
            "controls and procedures",
            "risk factors",
            "legal proceedings",
            "discussion and analysis",
            "market risk",
            "signatures",
        ),
    ),
    VetoSpec(
        "balance_sheet",
        "lead",
        "scored",
        (
            "cash flow",
            "cash flows",
            "revenue",
            "per share",
            "total assets",
            "common stock",
            "risk factors",
            "legal proceedings",
            "form 10-q",
            "guarantee",
            "acquisition",
        ),
    ),
    VetoSpec(
        "balance_sheet",
        "body",
        "scored",
        (
            "revenue",
            "per share",
            "total assets",
            "total liabilities",
            "current assets",
            "current liabilities",
            "deferred tax",
            "income tax",
            "maturity",
            "borrowings",
            "lease",
            "operating lease",
            "dividends",
            "common stock",
            "preferred stock",
            "inventories",
            "intangible",
            "goodwill",
            "derivative",
            "comprehensive income",
            "comprehensive loss",
            "acquisition",
            "deposits",
            "loans receivable",
            "deferred revenue",
        ),
    ),
    VetoSpec(
        "income_statement",
        "lead",
        "hard",
        ("gross profit", "premiums", "sales and marketing"),
    ),
    VetoSpec(
        "income_statement",
        "lead",
        "scored",
        ("revenue", "revenues", "segment", "acquisition", "research and development"),
    ),
    VetoSpec(
        "income_statement",
        "body",
        "scored",
        (
            "net income",
            "revenue",
            "revenues",
            "gross profit",
            "per share",
            "income tax",
            "depreciation",
            "amortization",
            "derivative",
            "acquisition",
            "premiums",
            "research and development",
            "sales and marketing",
        ),
    ),
    VetoSpec(
        "comprehensive_income",
        "lead",
        "scored",
        (
            "net income",
            "comprehensive income",
            "comprehensive loss",
            "other comprehensive",
            "accumulated other comprehensive",
            "reclassification",
        ),
    ),
    VetoSpec(
        "comprehensive_income",
        "body",
        "scored",
        (
            "cash flow",
            "net income",
            "pension",
            "actuarial",
            "income tax",
            "amortization",
            "derivative",
            "comprehensive income",
            "comprehensive loss",
            "other comprehensive",
            "accumulated other comprehensive",
            "reclassification",
        ),
    ),
    VetoSpec(
        "cash_flow",
        "lead",
        "hard",
        (
            "proceeds from",
            "per share",
            "borrowings",
            "lease",
            "common stock",
            "segment",
            "reportable segment",
            "issuer purchases",
        ),
    ),
    VetoSpec("cash_flow", "body", "hard", ("per share", "total assets")),
    VetoSpec("cash_flow", "lead", "scored", ("cash flow", "cash flows")),
    VetoSpec(
        "cash_flow",
        "body",
        "scored",
        (
            "cash flow",
            "cash flows",
            "operating activities",
            "investing activities",
            "financing activities",
            "net cash",
            "net income",
            "net loss",
            "revenue",
            "income tax",
            "lease",
            "common stock",
            "preferred stock",
            "vesting",
        ),
    ),
    VetoSpec(
        "equity_statement",
        "lead",
        "hard",
        ("weighted average", "discussion and analysis", "issuer purchases"),
    ),
    VetoSpec(
        "equity_statement",
        "body",
        "hard",
        ("total assets", "exercisable", "weighted average"),
    ),
    VetoSpec(
        "equity_statement",
        "lead",
        "scored",
        ("per share", "common stock", "comprehensive income", "other comprehensive"),
    ),
    VetoSpec(
        "equity_statement",
        "body",
        "scored",
        (
            "cash flow",
            "net income",
            "per share",
            "pension",
            "postretirement",
            "dividends",
            "common stock",
            "preferred stock",
            "vesting",
            "comprehensive income",
            "other comprehensive",
            "accumulated other comprehensive",
        ),
    ),
    VetoSpec("aoci_rollforward", "lead", "hard", ("income tax", "reclassification")),
    VetoSpec(
        "aoci_rollforward",
        "lead",
        "scored",
        (
            "net income",
            "comprehensive income",
            "comprehensive loss",
            "other comprehensive",
            "accumulated other comprehensive",
        ),
    ),
    VetoSpec(
        "aoci_rollforward",
        "body",
        "scored",
        (
            "cash flow",
            "pension",
            "postretirement",
            "actuarial",
            "income tax",
            "amortization",
            "comprehensive income",
            "comprehensive loss",
            "other comprehensive",
            "accumulated other comprehensive",
            "reclassification",
        ),
    ),
    VetoSpec(
        "segment_reporting",
        "lead",
        "scored",
        ("revenue", "gross profit", "operating income", "segment"),
    ),
    VetoSpec(
        "eps_reconciliation",
        "lead",
        "hard",
        (
            "comprehensive loss",
            "discussion and analysis",
            "acquisition",
            "issuer purchases",
        ),
    ),
    VetoSpec(
        "eps_reconciliation",
        "body",
        "hard",
        (
            "cash flow",
            "operating activities",
            "revenue",
            "total assets",
            "intangible",
            "amortization",
        ),
    ),
    VetoSpec(
        "eps_reconciliation",
        "lead",
        "scored",
        (
            "net income",
            "net loss",
            "revenue",
            "earnings per share",
            "per share",
            "income tax",
            "shares outstanding",
            "common stock",
            "weighted average",
            "dilutive",
            "anti-dilutive",
        ),
    ),
    VetoSpec(
        "eps_reconciliation",
        "body",
        "scored",
        (
            "net income",
            "per share",
            "dividends",
            "common stock",
            "preferred stock",
            "weighted average",
            "dilutive",
        ),
    ),
    VetoSpec("debt_maturity", "body", "hard", ("senior notes",)),
    VetoSpec(
        "debt_maturity",
        "lead",
        "scored",
        (
            "proceeds from",
            "maturity",
            "principal amount",
            "borrowings",
            "senior notes",
            "credit facility",
            "lease",
            "amortization",
            "letters of credit",
            "guarantee",
            "acquisition",
        ),
    ),
    VetoSpec(
        "lease_maturity",
        "lead",
        "hard",
        ("segment", "legal proceedings", "form 10-k", "contingencies"),
    ),
    VetoSpec("lease_maturity", "body", "hard", ("per share", "weighted average")),
    VetoSpec(
        "lease_maturity",
        "lead",
        "scored",
        (
            "cash flow",
            "cash flows",
            "lease",
            "operating lease",
            "common stock",
            "commitments",
        ),
    ),
    VetoSpec(
        "lease_maturity",
        "body",
        "scored",
        ("cash flow", "cash flows", "lease", "operating lease", "finance lease"),
    ),
    VetoSpec(
        "deferred_tax",
        "lead",
        "hard",
        (
            "cash flow",
            "revenue",
            "depreciation",
            "other comprehensive",
            "allowance for credit losses",
        ),
    ),
    VetoSpec(
        "deferred_tax",
        "body",
        "hard",
        ("balance at beginning", "balance at end", "additions"),
    ),
    VetoSpec(
        "deferred_tax",
        "lead",
        "scored",
        ("valuation allowance", "deferred tax", "income tax", "acquisition"),
    ),
    VetoSpec(
        "deferred_tax",
        "body",
        "scored",
        (
            "valuation allowance",
            "deferred tax",
            "income tax",
            "lease",
            "operating lease",
        ),
    ),
    VetoSpec(
        "tax_reconciliation",
        "lead",
        "hard",
        (
            "cash flow",
            "cash flows",
            "revenue",
            "revenues",
            "total assets",
            "lease",
            "preferred stock",
            "segment",
            "reportable segment",
            "unregistered sales",
            "form 10-k",
            "issuer purchases",
        ),
    ),
    VetoSpec(
        "tax_reconciliation", "body", "hard", ("revenue", "revenues", "per share")
    ),
    VetoSpec(
        "tax_reconciliation",
        "lead",
        "scored",
        ("income tax", "effective tax", "provision for income taxes"),
    ),
    VetoSpec(
        "tax_reconciliation",
        "body",
        "scored",
        ("income tax", "provision for income taxes"),
    ),
    VetoSpec("ppe", "body", "hard", ("acquisition",)),
    VetoSpec(
        "ppe",
        "lead",
        "scored",
        ("lease", "property, plant and equipment", "depreciation", "acquisition"),
    ),
    VetoSpec(
        "intangibles",
        "lead",
        "hard",
        ("cash flow", "revenue", "revenues", "gross profit", "income tax", "segment"),
    ),
    VetoSpec(
        "intangibles",
        "body",
        "hard",
        ("net income", "revenue", "revenues", "gross profit"),
    ),
    VetoSpec(
        "intangibles",
        "lead",
        "scored",
        (
            "depreciation",
            "intangible",
            "amortization",
            "goodwill",
            "indefinite-lived",
            "acquisition",
            "purchase price allocation",
        ),
    ),
    VetoSpec(
        "intangibles", "body", "scored", ("amortization", "goodwill", "acquisition")
    ),
    VetoSpec("inventory", "lead", "hard", ("property, plant and equipment",)),
    VetoSpec("inventory", "lead", "scored", ("lease", "inventories")),
    VetoSpec(
        "pension",
        "body",
        "hard",
        ("cash flow", "net income", "income tax", "hedging", "reclassification"),
    ),
    VetoSpec("pension", "lead", "scored", ("pension", "other comprehensive")),
    VetoSpec(
        "pension",
        "body",
        "scored",
        (
            "benefit obligation",
            "pension",
            "postretirement",
            "actuarial",
            "amortization",
            "comprehensive income",
            "comprehensive loss",
            "other comprehensive",
            "accumulated other comprehensive",
        ),
    ),
    VetoSpec(
        "stock_comp_rollforward",
        "lead",
        "hard",
        ("revenue", "sales and marketing", "issuer purchases"),
    ),
    VetoSpec("stock_comp_rollforward", "body", "hard", ("income tax", "amortization")),
    VetoSpec(
        "stock_comp_rollforward",
        "lead",
        "scored",
        (
            "per share",
            "lease",
            "common stock",
            "stock-based compensation",
            "vesting",
            "restricted stock",
        ),
    ),
    VetoSpec(
        "stock_comp_rollforward",
        "body",
        "scored",
        ("lease", "restricted stock", "weighted average"),
    ),
    VetoSpec("derivatives_hedging", "body", "hard", ("lease",)),
    VetoSpec(
        "derivatives_hedging",
        "lead",
        "scored",
        ("cash flow", "cash flows", "net income", "revenue", "derivative"),
    ),
    VetoSpec("derivatives_hedging", "body", "scored", ("cash flow", "derivative")),
    VetoSpec(
        "related_party",
        "lead",
        "scored",
        ("common stock", "related party", "related parties"),
    ),
)

LEAD_TEXT_CAP = 6000


def lead_channel_text(caption: str, prose_before: str) -> str:
    """The priced lead channel: caption + prose_before, tail-capped."""
    return caption + "\n" + prose_before[-LEAD_TEXT_CAP:]


def term_veto_hits(geometry: GeometryText) -> dict[str, dict[str, str]]:
    """First priced term-veto hit per family and tier.

    Matching is the pricing's own: normalized substring over the
    channel text; lead reads GeometryText.lead, body the grid.
    """
    texts = {
        "lead": normalize_text(geometry.lead),
        "body": normalize_text(geometry.grid_text),
    }
    hits: dict[str, dict[str, str]] = {}
    for spec in TERM_VETOES:
        text = texts[spec.channel]
        if not text:
            continue
        for term in spec.terms:
            if normalize_text(term) in text:
                tiers = hits.setdefault(spec.family, {})
                if spec.tier not in tiers:
                    tiers[spec.tier] = term
                break
    return hits
