"""Item taxonomy for current reports (8-K, 6-K)."""

from __future__ import annotations

from edgar_sec.domain.forms.common.models import ItemDefinition
from edgar_sec.domain.forms.families.annual.taxonomy import build_taxonomy_derived

FORM_8K_ITEMS: tuple[ItemDefinition, ...] = (
    ItemDefinition("ITEM 1.01", 1, ("Entry into a Material Definitive Agreement",)),
    ItemDefinition("ITEM 1.02", 1, ("Termination of a Material Definitive Agreement",)),
    ItemDefinition(
        "ITEM 2.01", 2, ("Completion of Acquisition or Disposition of Assets",)
    ),
    ItemDefinition("ITEM 2.02", 2, ("Results of Operations and Financial Condition",)),
    ItemDefinition(
        "ITEM 5.02",
        5,
        (
            (
                "Departure of Directors or Certain Officers; Election of Directors; "
                "Appointment of Certain Officers"
            ),
        ),
    ),
    ItemDefinition("ITEM 7.01", 7, ("Regulation FD Disclosure",)),
    ItemDefinition("ITEM 8.01", 8, ("Other Events",)),
    ItemDefinition("ITEM 9.01", 9, ("Financial Statements and Exhibits",)),
)

ITEMS: dict[str, str] = {d.item: d.names[0] for d in FORM_8K_ITEMS}
PARTS: tuple[str, ...] = ()

FORM_8K_DERIVED = build_taxonomy_derived(FORM_8K_ITEMS, PARTS)

# Exhibit-anchored 6-K taxonomy, adopted under the Step 18 census bar
# (.artifacts/run-logs/2026-11-08-sixk-census.md): the one drafted item
# that cleared per-item precision and coverage on the held-out slice.
FORM_6K_ITEMS: tuple[ItemDefinition, ...] = (
    ItemDefinition(
        "PRESS RELEASE",
        1,
        ("press release", "for immediate release"),
    ),
)

ITEMS_6K: dict[str, str] = {d.item: d.names[0] for d in FORM_6K_ITEMS}

FORM_6K_DERIVED = build_taxonomy_derived(FORM_6K_ITEMS, PARTS)

__all__ = [
    "FORM_6K_DERIVED",
    "FORM_6K_ITEMS",
    "FORM_8K_DERIVED",
    "FORM_8K_ITEMS",
    "ITEMS",
    "ITEMS_6K",
    "PARTS",
]
