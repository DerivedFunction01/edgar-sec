from __future__ import annotations

from edgar_sec.domain.forms.families.registration.taxonomy import (
    FORM_S1_DERIVED,
    FORM_S1_ITEMS,
    ITEMS,
    PARTS,
)


def test_form_s1_parts() -> None:
    assert len(PARTS) == 2
    assert PARTS == ("PART I", "PART II")
    assert len(FORM_S1_ITEMS) == 19
    assert len(ITEMS) == 19
    assert "ITEM 1" in ITEMS
    assert "ITEM 17" in ITEMS


def test_form_s1_derived_taxonomy() -> None:
    assert "early_items" in FORM_S1_DERIVED
    assert "late_items" in FORM_S1_DERIVED
    assert "matcher" in FORM_S1_DERIVED
    assert "ITEM 1" in FORM_S1_DERIVED["early_items"]
    assert "ITEM 16" in FORM_S1_DERIVED["late_items"]
    assert FORM_S1_DERIVED["late_item_re"].search("ITEM 16 Exhibits")


def test_form_s1_empirical_item_names() -> None:
    item_map = {item.item: item for item in FORM_S1_ITEMS}
    assert "selling stockholders" in item_map["ITEM 7"].names
    assert "legal matters" in item_map["ITEM 10"].names
    assert "experts" in item_map["ITEM 10"].names
    assert "where you can find more information" in item_map["ITEM 12"].names
    assert "where you can find additional information" in item_map["ITEM 12"].names

