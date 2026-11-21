"""Taxonomy for Form SD (Sections 1–3)."""

from __future__ import annotations

from edgar_sec.domain.forms.common.models import ItemDefinition

FORM_SD_ITEMS: tuple[ItemDefinition, ...] = (
    ItemDefinition(
        "ITEM 1.01",
        1,
        ("Conflict Minerals Disclosure and Report",),
    ),
    ItemDefinition(
        "ITEM 1.02",
        1,
        ("Exhibits", "Exhibit"),
    ),
    ItemDefinition(
        "ITEM 2.01",
        2,
        (
            "Resource Extraction Issuer Disclosure and Report",
            "Resource Extraction Issuer Disclosure Report",
        ),
    ),
    ItemDefinition(
        "ITEM 3.01",
        3,
        ("Exhibits", "Exhibit"),
    ),
)

SD_TITLES: tuple[str, ...] = (
    "form sd",
    "specialized disclosure report",
)

__all__ = ["FORM_SD_ITEMS", "SD_TITLES"]
