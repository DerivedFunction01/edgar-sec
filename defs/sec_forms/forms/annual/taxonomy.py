"""Part and Item taxonomy for annual reports (10-K, 20-F)."""

from __future__ import annotations

import re

from defs.regex import build_alternation
from defs.sec_forms.cover.models import ItemDefinition

PARTS: tuple[str, ...] = ("PART I", "PART II", "PART III", "PART IV")

FORM_10K_ITEMS: tuple[ItemDefinition, ...] = (
    # PART I
    ItemDefinition(
        "ITEM 1",
        1,
        (
            "business",
            "description of business",
            "business operations",
            "general business",
        ),
        early=True,
    ),
    ItemDefinition(
        "ITEM 1A",
        1,
        ("risk factors",),
        optional=True,
        early=True,
    ),
    ItemDefinition(
        "ITEM 1B",
        1,
        ("unresolved staff comments",),
        optional=True,
        early=True,
    ),
    ItemDefinition(
        "ITEM 1C",
        1,
        ("cybersecurity",),
        optional=True,
        early=True,
    ),
    ItemDefinition(
        "ITEM 2",
        1,
        ("properties", "property"),
        early=True,
    ),
    ItemDefinition(
        "ITEM 3",
        1,
        ("legal proceedings",),
        early=True,
    ),
    ItemDefinition(
        "ITEM 4",
        1,
        (
            "mine safety disclosures",
            "submission of matters to a vote of security holders",
            "reserved",
        ),
        optional=True,
        early=True,
    ),
    # PART II
    ItemDefinition(
        "ITEM 5",
        2,
        (
            "market for registrant's common equity, related stockholder matters and issuer purchases of equity securities",
            "market for registrant's common equity",
            "issuer purchases of equity securities",
        ),
    ),
    ItemDefinition(
        "ITEM 6",
        2,
        ("selected financial data",),
        optional=True,
    ),
    ItemDefinition(
        "ITEM 7",
        2,
        (
            "management's discussion and analysis of financial condition and results of operations",
            "management's discussion and analysis",
            "results of operations",
            "analysis of financial conditions",
        ),
    ),
    ItemDefinition(
        "ITEM 7A",
        2,
        (
            "quantitative and qualitative disclosures about market risk",
            "quantitative and qualitative disclosures",
            "about market risk",
        ),
        optional=True,
    ),
    ItemDefinition(
        "ITEM 8",
        2,
        (
            "financial statements and supplementary data",
            "financial statements",
            "supplementary data",
        ),
    ),
    ItemDefinition(
        "ITEM 9",
        2,
        (
            "changes in and disagreements with accountants on accounting and financial disclosure",
            "changes in and disagreements with accountants",
            "accounting and financial disclosures",
        ),
    ),
    ItemDefinition(
        "ITEM 9A",
        2,
        ("controls and procedures",),
    ),
    ItemDefinition(
        "ITEM 9B",
        2,
        ("other information",),
        optional=True,
    ),
    ItemDefinition(
        "ITEM 9C",
        2,
        (
            "disclosure regarding foreign jurisdictions that prevent inspections",
            "foreign jurisdictions that prevent inspections",
        ),
        optional=True,
    ),
    # PART III
    ItemDefinition(
        "ITEM 10",
        3,
        (
            "directors, executive officers and corporate governance",
            "directors, executive officers",
            "directors and executive officers",
        ),
    ),
    ItemDefinition(
        "ITEM 11",
        3,
        ("executive compensation",),
    ),
    ItemDefinition(
        "ITEM 12",
        3,
        (
            "security ownership of certain beneficial owners and management and related stockholder matters",
            "security ownership of certain beneficial owners",
            "security ownership",
        ),
    ),
    ItemDefinition(
        "ITEM 13",
        3,
        (
            "certain relationships and related transactions, and director independence",
            "certain relationships and related transactions",
            "certain relationships",
        ),
    ),
    ItemDefinition(
        "ITEM 14",
        3,
        (
            "principal accountant fees and services",
            "principal accountant fees",
        ),
    ),
    # PART IV
    ItemDefinition(
        "ITEM 15",
        4,
        (
            "exhibit and financial statement schedules",
            "exhibits, financial statement schedules",
            "exhibits",
        ),
    ),
    ItemDefinition(
        "ITEM 16",
        4,
        ("form 10-k summary",),
        optional=True,
    ),
)

FORM_20F_ITEMS: tuple[ItemDefinition, ...] = (
    # PART I
    ItemDefinition(
        "ITEM 1",
        1,
        (
            "identity of directors, senior management and advisers",
            "identity of directors",
        ),
        early=True,
    ),
    ItemDefinition(
        "ITEM 2",
        1,
        ("offer statistics and expected timetable", "offer statistics"),
        early=True,
    ),
    ItemDefinition(
        "ITEM 3",
        1,
        ("key information", "risk factors", "selected financial data"),
        early=True,
    ),
    ItemDefinition(
        "ITEM 4",
        1,
        (
            "information on the company",
            "description of business",
            "business overview",
            "property, plants and equipment",
        ),
        early=True,
    ),
    ItemDefinition(
        "ITEM 4A",
        1,
        ("unresolved staff comments",),
        optional=True,
        early=True,
    ),
    ItemDefinition(
        "ITEM 5",
        1,
        (
            "operating and financial review and prospects",
            "operating and financial review",
            "management's discussion",
            "results of operations",
        ),
        early=True,
    ),
    ItemDefinition(
        "ITEM 6",
        1,
        (
            "directors, senior management and employees",
            "directors and senior management",
            "executive compensation",
        ),
    ),
    ItemDefinition(
        "ITEM 7",
        1,
        ("major shareholders and related party transactions", "major shareholders"),
    ),
    ItemDefinition(
        "ITEM 8",
        1,
        ("financial information", "financial statements", "legal proceedings"),
    ),
    ItemDefinition(
        "ITEM 9",
        1,
        ("the offer and listing", "listing details", "markets"),
    ),
    ItemDefinition(
        "ITEM 10",
        1,
        (
            "additional information",
            "material contracts",
            "taxation",
            "exchange controls",
        ),
    ),
    ItemDefinition(
        "ITEM 11",
        1,
        (
            "quantitative and qualitative disclosures about market risk",
            "quantitative and qualitative",
        ),
        optional=True,
    ),
    ItemDefinition(
        "ITEM 12",
        1,
        (
            "description of securities other than equity securities",
            "description of securities",
        ),
        optional=True,
    ),
    # PART II
    ItemDefinition(
        "ITEM 13",
        2,
        ("defaults, dividend arrearages and delinquencies", "defaults"),
    ),
    ItemDefinition(
        "ITEM 14",
        2,
        (
            "material modifications to the rights of security holders",
            "material modifications",
        ),
    ),
    ItemDefinition(
        "ITEM 15",
        2,
        ("controls and procedures",),
    ),
    ItemDefinition(
        "ITEM 16",
        2,
        ("reserved",),
        optional=True,
    ),
    ItemDefinition(
        "ITEM 16A",
        2,
        ("audit committee financial expert",),
    ),
    ItemDefinition(
        "ITEM 16B",
        2,
        ("code of ethics",),
    ),
    ItemDefinition(
        "ITEM 16C",
        2,
        ("principal accountant fees and services", "principal accountant fees"),
    ),
    ItemDefinition(
        "ITEM 16D",
        2,
        ("exemptions from the listing standards for audit committees",),
        optional=True,
    ),
    ItemDefinition(
        "ITEM 16E",
        2,
        ("purchases of equity securities by the issuer and affiliated purchasers",),
        optional=True,
    ),
    ItemDefinition(
        "ITEM 16F",
        2,
        ("change in registrant's certifying accountant",),
        optional=True,
    ),
    ItemDefinition(
        "ITEM 16G",
        2,
        ("corporate governance",),
        optional=True,
    ),
    ItemDefinition(
        "ITEM 16H",
        2,
        ("mine safety disclosure",),
        optional=True,
    ),
    ItemDefinition(
        "ITEM 16I",
        2,
        ("disclosure regarding foreign jurisdictions that prevent inspections",),
        optional=True,
    ),
    # PART III
    ItemDefinition(
        "ITEM 17",
        3,
        ("financial statements",),
        optional=True,
    ),
    ItemDefinition(
        "ITEM 18",
        3,
        ("financial statements",),
    ),
    ItemDefinition(
        "ITEM 19",
        3,
        ("exhibits",),
    ),
)

ITEMS: dict[str, str] = {d.item: d.names[0].title() for d in FORM_10K_ITEMS}


def _normalize_token(text: str) -> str:
    sanitized = re.sub(r"[^a-z0-9]+", " ", text.lower())
    return " ".join(sanitized.split()).strip()


def build_taxonomy_derived(
    items: tuple[ItemDefinition, ...],
    parts: tuple[str, ...],
) -> dict[str, tuple[str, ...] | re.Pattern]:
    """Compile optimized lookup tuples and regexes for a form item taxonomy."""
    early_items = tuple(d.item for d in items if d.early)
    early_names = tuple(name for d in items if d.early for name in d.names)
    early_item_set = set(early_items)
    early_name_set = set(early_names)

    # An item or name is only 'late' if it is not also an early item/name
    late_items = tuple(
        d.item for d in items if not d.early and d.item not in early_item_set
    )
    late_names = tuple(
        name
        for d in items
        if not d.early
        for name in d.names
        if name not in early_name_set
    )

    late_parts = tuple(p for p in parts if p not in ("PART I", "PART 1"))

    late_item_re = re.compile(
        rf"^\s*(?:{build_alternation(list(late_items + late_parts), auto_escape=True)})\b",
        re.IGNORECASE,
    )

    toc_keywords = tuple(
        early_items
        + early_names
        + ("part i", "part 1")
        + late_parts
        + ("reserved", "[reserved]", "(reserved)")
    )

    from defs.text.automaton import compile_lexical_matcher

    norm_toc = tuple(_normalize_token(t) for t in toc_keywords if _normalize_token(t))
    norm_late = tuple(_normalize_token(t) for t in late_names if _normalize_token(t))
    norm_early = tuple(_normalize_token(t) for t in early_names if _normalize_token(t))

    matcher = compile_lexical_matcher(
        {
            "toc_keywords": norm_toc,
            "late_names": norm_late,
            "early_names": norm_early,
        }
    )

    return {
        "early_items": early_items,
        "early_names": early_names,
        "late_items": late_items,
        "late_names": late_names,
        "late_parts": late_parts,
        "late_item_re": late_item_re,
        "toc_keywords": toc_keywords,
        "norm_toc_keywords": norm_toc,
        "norm_late_names": norm_late,
        "norm_early_names": norm_early,
        "matcher": matcher,
    }


FORM_10K_DERIVED = build_taxonomy_derived(FORM_10K_ITEMS, PARTS)
FORM_20F_DERIVED = build_taxonomy_derived(
    FORM_20F_ITEMS, ("PART I", "PART II", "PART III")
)

__all__ = [
    "FORM_10K_DERIVED",
    "FORM_10K_ITEMS",
    "FORM_20F_DERIVED",
    "FORM_20F_ITEMS",
    "ITEMS",
    "PARTS",
    "build_taxonomy_derived",
]
