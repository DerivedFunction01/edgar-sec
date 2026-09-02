"""Part and Item taxonomy for quarterly reports (10-Q)."""

from __future__ import annotations

from defs.sec_forms.cover.models import ItemDefinition
from defs.sec_forms.forms.annual.taxonomy import build_taxonomy_derived

PARTS: tuple[str, ...] = ("PART I", "PART II")

FORM_10Q_ITEMS: tuple[ItemDefinition, ...] = (
    # PART I - Financial Information
    ItemDefinition(
        "ITEM 1",
        1,
        ("financial statements", "condensed consolidated financial statements"),
        early=True,
    ),
    ItemDefinition(
        "ITEM 2",
        1,
        (
            "management's discussion and analysis of financial condition and results of operations",
            "management's discussion and analysis",
            "results of operations",
        ),
        early=True,
    ),
    ItemDefinition(
        "ITEM 3",
        1,
        (
            "quantitative and qualitative disclosures about market risk",
            "quantitative and qualitative",
        ),
        optional=True,
        early=True,
    ),
    ItemDefinition(
        "ITEM 4",
        1,
        ("controls and procedures",),
        early=True,
    ),
    # PART II - Other Information
    ItemDefinition(
        "ITEM 1",
        2,
        ("legal proceedings",),
        optional=True,
    ),
    ItemDefinition(
        "ITEM 1A",
        2,
        ("risk factors",),
        optional=True,
    ),
    ItemDefinition(
        "ITEM 2",
        2,
        ("unregistered sales of equity securities and use of proceeds",),
        optional=True,
    ),
    ItemDefinition(
        "ITEM 3",
        2,
        ("defaults upon senior securities",),
        optional=True,
    ),
    ItemDefinition(
        "ITEM 4",
        2,
        ("mine safety disclosures",),
        optional=True,
    ),
    ItemDefinition(
        "ITEM 5",
        2,
        ("other information",),
        optional=True,
    ),
    ItemDefinition(
        "ITEM 6",
        2,
        ("exhibits",),
    ),
)

ITEMS: dict[str, str] = {d.item: d.names[0].title() for d in FORM_10Q_ITEMS}

FORM_10Q_DERIVED = build_taxonomy_derived(FORM_10Q_ITEMS, PARTS)

__all__ = [
    "FORM_10Q_DERIVED",
    "FORM_10Q_ITEMS",
    "ITEMS",
    "PARTS",
]
