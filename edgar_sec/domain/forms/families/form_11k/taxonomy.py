"""Item taxonomy for Form 11-K employee plan annual reports."""

from __future__ import annotations

from edgar_sec.domain.forms.common.models import ItemDefinition

FORM_11K_ITEMS: tuple[ItemDefinition, ...] = (
    ItemDefinition(
        "ITEM 1",
        1,
        ("changes in the plan",),
        optional=True,
    ),
    ItemDefinition(
        "ITEM 2",
        1,
        ("changes in investment policy",),
        optional=True,
    ),
    ItemDefinition(
        "ITEM 3",
        1,
        ("contributions under the plan",),
        optional=True,
    ),
    ItemDefinition(
        "ITEM 4",
        1,
        (
            "financial statements and supplemental schedules",
            "participating employees",
            "report of independent registered public accounting firm",
            "statements of net assets available for benefits",
            "statement of changes in net assets available for benefits",
            "notes to financial statements",
        ),
    ),
    ItemDefinition(
        "ITEM 5",
        1,
        ("administration of the plan",),
        optional=True,
    ),
    ItemDefinition(
        "ITEM 9",
        1,
        ("financial statements and exhibits",),
        optional=True,
    ),
)

FORM_11K_TITLES: tuple[str, ...] = (
    "form 11-k",
    "annual reports of employee stock purchase, savings and similar plans",
    "financial statements and supplemental schedules",
)

__all__ = [
    "FORM_11K_ITEMS",
    "FORM_11K_TITLES",
]
