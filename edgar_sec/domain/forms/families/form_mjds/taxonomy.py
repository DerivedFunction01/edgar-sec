"""MJDS tail taxonomies shared by the F-7/F-8/F-9/F-10/F-80 forms.

Two evidenced tails: a legends block (Items 1-4) on F-7, F-8 and F-80,
and an undertakings block (Items 1-2) on F-9, F-10, F-8 and F-80. The
F-10/A Items 8-10 block is a recorded variant, not a third taxonomy.
"""

from __future__ import annotations

from edgar_sec.domain.forms.common.models import ItemDefinition

MJDS_LEGENDS_ITEMS: tuple[ItemDefinition, ...] = (
    ItemDefinition(
        "ITEM 1",
        2,
        ("home jurisdiction document(s)", "home jurisdiction documents"),
    ),
    ItemDefinition(
        "ITEM 2",
        2,
        ("informational legends", "informational legend"),
    ),
    ItemDefinition(
        "ITEM 3",
        2,
        ("incorporation of certain information by reference",),
    ),
    ItemDefinition("ITEM 4", 2, ("list of documents filed",)),
)

MJDS_UNDERTAKINGS_ITEMS: tuple[ItemDefinition, ...] = (
    ItemDefinition(
        "ITEM 1",
        2,
        ("undertakings", "undertaking(s)", "undertaking"),
    ),
    ItemDefinition("ITEM 2", 2, ("consent to service of process",)),
)

FORM_F7_ITEMS: tuple[ItemDefinition, ...] = MJDS_LEGENDS_ITEMS

FORM_F8_ITEMS: tuple[ItemDefinition, ...] = (
    *MJDS_LEGENDS_ITEMS,
    *MJDS_UNDERTAKINGS_ITEMS,
)

FORM_F9_ITEMS: tuple[ItemDefinition, ...] = MJDS_UNDERTAKINGS_ITEMS

FORM_F10_ITEMS: tuple[ItemDefinition, ...] = MJDS_UNDERTAKINGS_ITEMS

FORM_F80_ITEMS: tuple[ItemDefinition, ...] = (
    *MJDS_LEGENDS_ITEMS,
    *MJDS_UNDERTAKINGS_ITEMS,
)

# Shelf-prospectus section headings for the F-9/F-10 in-body prospectus,
# harvested from the probed F-10 base-shelf table of contents; the split
# tax titles expand the combined "certain income tax considerations".
MJDS_PROSPECTUS_HEADINGS: tuple[str, ...] = (
    "about this prospectus",
    "documents incorporated by reference",
    "consolidated capitalization",
    "use of proceeds",
    "plan of distribution",
    "description of debt securities",
    "description of securities",
    "risk factors",
    "enforceability of certain civil liabilities",
    "enforceability of civil liabilities",
    "certain income tax considerations",
    "certain canadian federal income tax considerations",
    "certain united states federal income tax considerations",
    "legal matters",
    "experts",
    "documents filed as part of the registration statement",
    "annual information form",
    "management's discussion and analysis",
    "eligibility for investment",
    "exchange controls",
)

# One probed F-10/A specimen carries this F-3-style block instead of the
# undertakings tail; recorded here so the engine step can classify it.
FORM_F10_AMENDMENT_VARIANT_ITEMS: tuple[ItemDefinition, ...] = (
    ItemDefinition(
        "ITEM 8",
        2,
        ("indemnification of directors and officers",),
        optional=True,
    ),
    ItemDefinition(
        "ITEM 9",
        2,
        ("exhibits", "exhibits and financial statement schedules"),
        optional=True,
    ),
    ItemDefinition("ITEM 10", 2, ("undertakings",), optional=True),
)

__all__ = [
    "FORM_F10_AMENDMENT_VARIANT_ITEMS",
    "FORM_F10_ITEMS",
    "FORM_F7_ITEMS",
    "FORM_F80_ITEMS",
    "FORM_F8_ITEMS",
    "FORM_F9_ITEMS",
    "MJDS_LEGENDS_ITEMS",
    "MJDS_PROSPECTUS_HEADINGS",
    "MJDS_UNDERTAKINGS_ITEMS",
]
