"""Section taxonomy for Rule 424 prospectuses and supplements: the
recurring prospectus skeleton evidenced by filed specimens' contents
blocks and headings; single-specimen deal sections are excluded.
"""

from __future__ import annotations

from edgar_sec.domain.forms.common.models import ItemDefinition

FORM_424B_ITEMS: tuple[ItemDefinition, ...] = (
    ItemDefinition(
        "ABOUT THIS PROSPECTUS",
        1,
        (
            "about this prospectus",
            "about this prospectus supplement",
        ),
        early=True,
    ),
    ItemDefinition(
        "PROSPECTUS SUMMARY",
        1,
        (
            "prospectus summary",
            "prospectus supplement summary",
            "summary information",
            "summary",
        ),
        early=True,
    ),
    ItemDefinition(
        "FORWARD-LOOKING STATEMENTS",
        1,
        (
            "forward-looking statements",
            "cautionary note regarding forward-looking statements",
            "cautionary statement regarding forward-looking statements",
            "disclosure regarding forward-looking statements",
        ),
        early=True,
    ),
    ItemDefinition(
        "RISK FACTORS",
        1,
        (
            "risk factors",
            "selected risk considerations",
        ),
        early=True,
    ),
    ItemDefinition(
        "RATIO OF EARNINGS TO FIXED CHARGES",
        1,
        (
            "ratio of earnings to fixed charges",
            "ratios of earnings to fixed charges and combined fixed charges "
            "and preferred stock dividends",
        ),
        optional=True,
        early=True,
    ),
    ItemDefinition(
        "THE OFFERING",
        1,
        ("the offering",),
        optional=True,
        early=True,
    ),
    ItemDefinition(
        "USE OF PROCEEDS",
        1,
        ("use of proceeds",),
        early=True,
    ),
    ItemDefinition(
        "SELLING STOCKHOLDERS",
        1,
        (
            "selling stockholders",
            "selling security holders",
            "selling securityholders",
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
            "description of warrants",
        ),
    ),
    ItemDefinition(
        "OUR COMPANY",
        1,
        ("our company",),
        optional=True,
    ),
    ItemDefinition(
        "TAX CONSIDERATIONS",
        1,
        (
            "u.s. federal income tax considerations",
            "material u.s. federal income tax considerations",
            "certain u.s. federal income tax considerations",
            "additional u.s. federal income tax considerations",
        ),
        optional=True,
    ),
    ItemDefinition(
        "LEGAL MATTERS",
        1,
        ("legal matters",),
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
            "incorporation by reference",
            "information incorporated by reference",
            "incorporation of certain documents by reference",
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
    ),
)

#: Document kinds in the merged family, most specific first: the first
#: kind whose phrases appear in the cover classifies the document.
FORM_424B_DOCUMENT_KINDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("pricing_supplement", ("pricing supplement",)),
    ("preliminary_prospectus_supplement", ("preliminary prospectus supplement",)),
    ("prospectus_supplement", ("prospectus supplement",)),
    ("preliminary_prospectus", ("preliminary prospectus",)),
    ("prospectus", ("prospectus",)),
)

FORM_424B_TITLES: tuple[str, ...] = (
    "prospectus",
    "prospectus supplement",
    "preliminary prospectus",
    "preliminary prospectus supplement",
    "pricing supplement",
)

__all__ = [
    "FORM_424B_DOCUMENT_KINDS",
    "FORM_424B_ITEMS",
    "FORM_424B_TITLES",
]
