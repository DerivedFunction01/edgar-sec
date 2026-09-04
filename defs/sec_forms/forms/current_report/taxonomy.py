"""Item taxonomy for current reports (8-K, 6-K)."""

from __future__ import annotations

from defs.sec_forms.cover.models import ItemDefinition
from defs.sec_forms.forms.annual.taxonomy import build_taxonomy_derived

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

__all__ = [
    "FORM_8K_DERIVED",
    "FORM_8K_ITEMS",
    "ITEMS",
    "PARTS",
]
