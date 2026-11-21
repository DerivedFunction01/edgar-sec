"""Section taxonomy for Form F-3: the shelf prospectus heading
vocabulary and the closed Part II Items 8-10 evidenced by specimens.
"""

from __future__ import annotations

from edgar_sec.domain.forms.common.models import ItemDefinition

FORM_F3_ITEMS: tuple[ItemDefinition, ...] = (
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
        "CAPITALIZATION",
        1,
        ("capitalization",),
        optional=True,
        early=True,
    ),
    ItemDefinition(
        "DILUTION",
        1,
        ("dilution",),
        optional=True,
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
        optional=True,
    ),
    ItemDefinition(
        "INCORPORATION BY REFERENCE",
        1,
        (
            "incorporation of certain information by reference",
            "incorporation by reference",
        ),
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
)

__all__ = ["FORM_F3_ITEMS"]
