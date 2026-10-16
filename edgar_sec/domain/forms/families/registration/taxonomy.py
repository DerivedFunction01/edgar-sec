"""Part and Item taxonomy for registration statements (Form S-1)."""

from __future__ import annotations

from edgar_sec.domain.forms.common.models import ItemDefinition
from edgar_sec.domain.forms.families.annual.taxonomy import build_taxonomy_derived

PARTS: tuple[str, ...] = ("PART I", "PART II")

FORM_S1_ITEMS: tuple[ItemDefinition, ...] = (
    ItemDefinition(
        "ITEM 1",
        1,
        (
            "forepart of the registration statement and outside front cover page of prospectus",
            "outside front cover page of prospectus",
            "front cover page of prospectus",
        ),
        early=True,
    ),
    ItemDefinition(
        "ITEM 2",
        1,
        (
            "inside front and outside back cover pages of prospectus",
            "inside front and outside back cover pages",
        ),
        optional=True,
        early=True,
    ),
    ItemDefinition(
        "ITEM 3",
        1,
        (
            "summary information, risk factors and ratio of earnings to fixed charges",
            "summary information and risk factors",
            "prospectus summary",
            "summary",
            "risk factors",
        ),
        early=True,
    ),
    ItemDefinition(
        "ITEM 4",
        1,
        ("use of proceeds",),
        early=True,
    ),
    ItemDefinition(
        "ITEM 5",
        1,
        ("determination of offering price",),
        early=True,
    ),
    ItemDefinition(
        "ITEM 6",
        1,
        ("dilution",),
        early=True,
    ),
    ItemDefinition(
        "ITEM 7",
        1,
        ("selling security holders", "selling stockholders", "selling shareholders"),
        optional=True,
        early=True,
    ),
    ItemDefinition(
        "ITEM 8",
        1,
        ("plan of distribution", "underwriting"),
        early=True,
    ),
    ItemDefinition(
        "ITEM 9",
        1,
        (
            "description of securities to be registered",
            "description of capital stock",
            "description of securities",
        ),
    ),
    ItemDefinition(
        "ITEM 10",
        1,
        (
            "interests of named experts and counsel",
            "legal matters",
            "experts",
        ),
        optional=True,
    ),
    ItemDefinition(
        "ITEM 11",
        1,
        (
            "information with respect to the registrant",
            "business",
            "description of business",
            "management's discussion and analysis of financial condition and results of operations",
            "financial statements",
        ),
    ),
    ItemDefinition(
        "ITEM 11A",
        1,
        ("material changes",),
        optional=True,
    ),
    ItemDefinition(
        "ITEM 12",
        1,
        (
            "incorporation of certain information by reference",
            "incorporation by reference",
            "where you can find more information",
            "where you can find additional information",
        ),
        optional=True,
    ),
    ItemDefinition(
        "ITEM 12A",
        1,
        (
            "disclosure of commission position on indemnification for securities act liabilities",
            "disclosure of commission position on indemnification",
        ),
        optional=True,
    ),
    ItemDefinition(
        "ITEM 13",
        2,
        (
            "other expenses of issuance and distribution",
            "expenses of issuance and distribution",
        ),
    ),
    ItemDefinition(
        "ITEM 14",
        2,
        ("indemnification of directors and officers",),
    ),
    ItemDefinition(
        "ITEM 15",
        2,
        (
            "recent sales of unregistered securities",
            "sales of unregistered securities",
        ),
        optional=True,
    ),
    ItemDefinition(
        "ITEM 16",
        2,
        (
            "exhibits and financial statement schedules",
            "exhibits",
            "index to exhibits",
            "exhibit index",
        ),
    ),
    ItemDefinition(
        "ITEM 17",
        2,
        ("undertakings",),
    ),
)

ITEMS: dict[str, str] = {d.item: d.names[0].title() for d in FORM_S1_ITEMS}

FORM_S1_DERIVED = build_taxonomy_derived(FORM_S1_ITEMS, PARTS)

__all__ = [
    "FORM_S1_DERIVED",
    "FORM_S1_ITEMS",
    "ITEMS",
    "PARTS",
]
