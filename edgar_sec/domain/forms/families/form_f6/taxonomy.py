"""Form F-6 taxonomy for the depositary registration statement.

Items 1-2 sit in Part I as the cross-reference sheet; Items 3-4 are
Part II. A filed variant renumbers the Part II pair as Items 1-2.
"""

from __future__ import annotations

from edgar_sec.domain.forms.common.models import ItemDefinition

FORM_F6_ITEMS: tuple[ItemDefinition, ...] = (
    ItemDefinition(
        "ITEM 1",
        1,
        ("description of securities to be registered",),
    ),
    ItemDefinition("ITEM 2", 1, ("available information",)),
    ItemDefinition(
        "ITEM 3",
        2,
        ("exhibits", "index to exhibits", "exhibit index"),
    ),
    ItemDefinition("ITEM 4", 2, ("undertakings",)),
    ItemDefinition(
        "ITEM 1",
        2,
        ("exhibits", "index to exhibits", "exhibit index"),
        optional=True,
    ),
    ItemDefinition("ITEM 2", 2, ("undertakings",), optional=True),
)

__all__ = ["FORM_F6_ITEMS"]
