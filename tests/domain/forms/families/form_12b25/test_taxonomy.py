from __future__ import annotations

from edgar_sec.domain.forms.families.form_12b25.taxonomy import (
    FORM_12B25_ITEMS,
    PARTS,
)


def test_form_12b25_parts() -> None:
    assert len(PARTS) == 4
    assert PARTS == ("PART I", "PART II", "PART III", "PART IV")


def test_form_12b25_items() -> None:
    assert [item.item for item in FORM_12B25_ITEMS] == [
        "PART I",
        "PART II",
        "PART III",
        "PART IV",
    ]
    assert [item.part for item in FORM_12B25_ITEMS] == [1, 2, 3, 4]
    for item in FORM_12B25_ITEMS:
        assert item.names


def test_form_12b25_item_names() -> None:
    item_map = {item.item: item for item in FORM_12B25_ITEMS}
    assert item_map["PART I"].names[0] == "registrant information"
    assert item_map["PART II"].names[0] == "rules 12b-25(b) and (c)"
    assert item_map["PART III"].names[0] == "narrative"
    assert item_map["PART IV"].names[0] == "other information"
    assert "part i — registrant information" in item_map["PART I"].names
    assert "part iv — other information" in item_map["PART IV"].names
