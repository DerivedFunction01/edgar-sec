from __future__ import annotations

from edgar_sec.domain.forms.families.beneficial_ownership.taxonomy import (
    SCHEDULE_13D_ITEMS,
    SCHEDULE_13G_ITEMS,
)


def test_schedule_13d_taxonomy_covers_items_one_through_seven() -> None:
    assert tuple(item.item for item in SCHEDULE_13D_ITEMS) == tuple(
        f"ITEM {i}" for i in range(1, 8)
    )


def test_schedule_13g_taxonomy_covers_items_one_through_ten() -> None:
    assert tuple(item.item for item in SCHEDULE_13G_ITEMS) == tuple(
        f"ITEM {i}" for i in range(1, 11)
    )
