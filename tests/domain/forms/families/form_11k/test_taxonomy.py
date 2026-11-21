from __future__ import annotations

from edgar_sec.domain.forms.families.form_11k.taxonomy import FORM_11K_ITEMS


def test_form_11k_items() -> None:
    assert [item.item for item in FORM_11K_ITEMS] == [
        "ITEM 1",
        "ITEM 2",
        "ITEM 3",
        "ITEM 4",
        "ITEM 5",
        "ITEM 9",
    ]
    for item in FORM_11K_ITEMS:
        assert item.names


def test_form_11k_item_names() -> None:
    item_map = {item.item: item for item in FORM_11K_ITEMS}
    assert item_map["ITEM 1"].names[0] == "changes in the plan"
    assert item_map["ITEM 2"].names[0] == "changes in investment policy"
    assert item_map["ITEM 3"].names[0] == "contributions under the plan"
    assert item_map["ITEM 4"].names[0] == (
        "financial statements and supplemental schedules"
    )
    assert "statements of net assets available for benefits" in (
        item_map["ITEM 4"].names
    )
    assert item_map["ITEM 9"].names[0] == "financial statements and exhibits"
    names = [name for item in FORM_11K_ITEMS for name in item.names]
    assert len(names) == len(set(names))
