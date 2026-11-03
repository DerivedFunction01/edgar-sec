"""Section taxonomy for Form F-4: the transaction prospectus heading
vocabulary and Part II Items 20-22; older POS specimens carry an
Item 16 Exhibits numbering, recorded as an era variant.
"""

from __future__ import annotations

from edgar_sec.domain.forms.common.models import ItemDefinition

FORM_F4_ITEMS: tuple[ItemDefinition, ...] = (
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
        "TERMS OF THE TRANSACTION",
        1,
        (
            "terms of the transaction",
            "the merger",
            "the transaction",
        ),
        early=True,
    ),
    ItemDefinition(
        "PRO FORMA FINANCIAL INFORMATION",
        1,
        (
            "pro forma financial information",
            "unaudited pro forma financial information",
        ),
        optional=True,
        early=True,
    ),
    ItemDefinition(
        "USE OF PROCEEDS",
        1,
        ("use of proceeds",),
        optional=True,
    ),
    ItemDefinition(
        "CAPITALIZATION",
        1,
        ("capitalization",),
        optional=True,
    ),
    ItemDefinition(
        "DILUTION",
        1,
        ("dilution",),
        optional=True,
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
        optional=True,
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
        optional=True,
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
    ItemDefinition(
        "ITEM 20",
        2,
        ("indemnification of directors and officers",),
    ),
    ItemDefinition(
        "ITEM 21",
        2,
        (
            "exhibits and financial statement schedules",
            "exhibits",
            "index to exhibits",
            "exhibit index",
        ),
    ),
    ItemDefinition(
        "ITEM 22",
        2,
        ("undertakings",),
    ),
    # Era variant: an older POS specimen numbers Exhibits as Item 16.
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
)

__all__ = ["FORM_F4_ITEMS"]
