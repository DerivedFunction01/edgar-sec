"""Section taxonomy for Forms F-1 and F-2: the prospectus heading
vocabulary and closed Part II item sets evidenced by filed specimens.
F-2 is the era-closed variant: its Part II appears under both the
Items 8-10 numbering (its own) and the Items 14-17 S-1 numbering.
"""

from __future__ import annotations

from edgar_sec.domain.forms.common.models import ItemDefinition

_PROSPECTUS_ITEMS: tuple[ItemDefinition, ...] = (
    ItemDefinition(
        "PROSPECTUS SUMMARY",
        1,
        (
            "prospectus summary",
            "summary information",
            "summary",
        ),
        early=True,
    ),
    ItemDefinition(
        "RISK FACTORS",
        1,
        ("risk factors",),
        early=True,
    ),
    ItemDefinition(
        "USE OF PROCEEDS",
        1,
        ("use of proceeds",),
        early=True,
    ),
    ItemDefinition(
        "DETERMINATION OF OFFERING PRICE",
        1,
        ("determination of offering price",),
        optional=True,
        early=True,
    ),
    ItemDefinition(
        "DIVIDEND POLICY",
        1,
        ("dividend policy",),
        optional=True,
        early=True,
    ),
    ItemDefinition(
        "CAPITALIZATION",
        1,
        ("capitalization",),
        early=True,
    ),
    ItemDefinition(
        "DILUTION",
        1,
        ("dilution",),
        early=True,
    ),
    ItemDefinition(
        "SELLING SHAREHOLDERS",
        1,
        (
            "selling shareholders",
            "selling security holders",
            "selling stockholders",
        ),
        optional=True,
    ),
    ItemDefinition(
        "PLAN OF DISTRIBUTION",
        1,
        ("plan of distribution",),
    ),
    ItemDefinition(
        "UNDERWRITING",
        1,
        ("underwriting",),
        optional=True,
    ),
    ItemDefinition(
        "DESCRIPTION OF SECURITIES",
        1,
        (
            "description of securities",
            "description of capital stock",
        ),
    ),
    ItemDefinition(
        "ENFORCEABILITY OF CIVIL LIABILITIES",
        1,
        ("enforceability of civil liabilities",),
        optional=True,
    ),
    ItemDefinition(
        "EXCHANGE CONTROLS",
        1,
        ("exchange controls",),
        optional=True,
    ),
    ItemDefinition(
        "TAX CONSIDERATIONS",
        1,
        (
            "tax considerations",
            "material tax considerations",
            "certain tax considerations",
            "canadian tax considerations",
            "u.s. federal income tax considerations",
        ),
        optional=True,
    ),
    ItemDefinition(
        "LEGAL MATTERS",
        1,
        ("legal matters",),
        optional=True,
    ),
    ItemDefinition(
        "EXPERTS",
        1,
        ("experts",),
    ),
    ItemDefinition(
        "INCORPORATION BY REFERENCE",
        1,
        (
            "incorporation of certain information by reference",
            "incorporation by reference",
        ),
        optional=True,
    ),
    ItemDefinition(
        "WHERE YOU CAN FIND MORE INFORMATION",
        1,
        (
            "where you can find more information",
            "where you can find additional information",
        ),
        optional=True,
    ),
)

FORM_F1_ITEMS: tuple[ItemDefinition, ...] = (
    *_PROSPECTUS_ITEMS,
    ItemDefinition(
        "ITEM 6",
        2,
        ("indemnification of directors and officers",),
    ),
    ItemDefinition(
        "ITEM 7",
        2,
        (
            "recent sales of unregistered securities",
            "sales of unregistered securities",
        ),
        optional=True,
    ),
    ItemDefinition(
        "ITEM 8",
        2,
        (
            "exhibits and financial statement schedules",
            "exhibits",
            "index to exhibits",
            "exhibit index",
        ),
    ),
    ItemDefinition(
        "ITEM 9",
        2,
        ("undertakings",),
    ),
)

FORM_F2_ITEMS: tuple[ItemDefinition, ...] = (
    *_PROSPECTUS_ITEMS,
    ItemDefinition(
        "ITEM 8",
        2,
        ("indemnification of directors and officers",),
    ),
    ItemDefinition(
        "ITEM 9",
        2,
        (
            "exhibits",
            "index to exhibits",
            "exhibit index",
        ),
    ),
    ItemDefinition(
        "ITEM 10",
        2,
        ("undertakings",),
    ),
    # Era variant: earliest specimens carry the S-1 Part II numbering.
    ItemDefinition(
        "ITEM 14",
        2,
        ("indemnification of directors and officers",),
        optional=True,
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
        optional=True,
    ),
    ItemDefinition(
        "ITEM 17",
        2,
        ("undertakings",),
        optional=True,
    ),
)

__all__ = [
    "FORM_F1_ITEMS",
    "FORM_F2_ITEMS",
]
