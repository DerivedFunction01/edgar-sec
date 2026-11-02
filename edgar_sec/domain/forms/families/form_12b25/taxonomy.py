"""Part taxonomy for Form 12b-25 notifications of late filing."""

from __future__ import annotations

from edgar_sec.domain.forms.common.models import ItemDefinition

PARTS: tuple[str, ...] = ("PART I", "PART II", "PART III", "PART IV")

FORM_12B25_ITEMS: tuple[ItemDefinition, ...] = (
    ItemDefinition(
        "PART I",
        1,
        (
            "registrant information",
            "part i — registrant information",
            "part i – registrant information",
            "part i - registrant information",
            "part i-- registrant information",
            "part i--registrant information",
            "part i- registrant information",
            "part i registrant information",
        ),
    ),
    ItemDefinition(
        "PART II",
        2,
        (
            "rules 12b-25(b) and (c)",
            "part ii — rules 12b-25(b) and (c)",
            "part ii – rules 12b-25(b) and (c)",
            "part ii - rules 12b-25(b) and (c)",
            "part ii-- rules 12b-25(b) and (c)",
            "part ii--rules 12b-25(b) and (c)",
            "part ii- rules 12b-25(b) and (c)",
            "rules 12b-25 (b) and (c)",
        ),
    ),
    ItemDefinition(
        "PART III",
        3,
        (
            "narrative",
            "part iii — narrative",
            "part iii – narrative",
            "part iii - narrative",
            "part iii-- narrative",
            "part iii--narrative",
            "part iii- narrative",
            "part iii narrative",
        ),
    ),
    ItemDefinition(
        "PART IV",
        4,
        (
            "other information",
            "part iv — other information",
            "part iv – other information",
            "part iv - other information",
            "part iv-- other information",
            "part iv--other information",
            "part iv- other information",
            "part iv other information",
        ),
    ),
)

__all__ = [
    "FORM_12B25_ITEMS",
    "PARTS",
]
