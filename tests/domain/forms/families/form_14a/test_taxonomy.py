from __future__ import annotations

from edgar_sec.domain.forms.families.form_14a.taxonomy import FORM_14A_ITEMS


def test_form_14a_items_cover_schedule_14a() -> None:
    assert [item.item for item in FORM_14A_ITEMS] == [
        f"ITEM {number}" for number in range(1, 26)
    ]
    for item in FORM_14A_ITEMS:
        assert item.names


def test_form_14a_item_names() -> None:
    item_map = {item.item: item for item in FORM_14A_ITEMS}
    assert item_map["ITEM 1"].names[0] == "date, time and place of meeting"
    assert item_map["ITEM 7"].names[0] == "directors and executive officers"
    assert "election of directors" in item_map["ITEM 7"].names
    assert item_map["ITEM 8"].names[0] == (
        "compensation of directors and executive officers"
    )
    assert "executive compensation" in item_map["ITEM 8"].names
    assert item_map["ITEM 22"].optional is True
    assert item_map["ITEM 24"].names[0] == (
        "shareholder approval of executive compensation"
    )
    assert item_map["ITEM 25"].names[0] == "exhibits"
