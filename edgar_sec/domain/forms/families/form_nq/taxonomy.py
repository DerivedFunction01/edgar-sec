"""Section taxonomy for Form N-Q quarterly schedules of portfolio
holdings: the schedule itself and the closing item blocks.
"""

from __future__ import annotations

from edgar_sec.domain.forms.common.models import ItemDefinition

FORM_NQ_ITEMS: tuple[ItemDefinition, ...] = (
    ItemDefinition(
        "SCHEDULE OF INVESTMENTS",
        1,
        (
            "schedule of investments",
            "schedule of portfolio holdings",
            "consolidated schedule of investments",
        ),
        early=True,
    ),
    ItemDefinition(
        "CONTROLS AND PROCEDURES",
        2,
        ("controls and procedures",),
    ),
    ItemDefinition(
        "EXHIBITS",
        3,
        ("exhibits",),
        optional=True,
    ),
)

__all__ = ["FORM_NQ_ITEMS"]
