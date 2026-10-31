from __future__ import annotations

from edgar_sec.domain.forms.families.registration.taxonomy import (
    FORM_S1_DERIVED,
    FORM_S1_ITEMS,
    FORM_S3_DERIVED,
    FORM_S3_ITEMS,
    FORM_S4_DERIVED,
    FORM_S4_ITEMS,
    FORM_S8_DERIVED,
    FORM_S8_ITEMS,
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


def test_form_s3_taxonomy_and_derived() -> None:
    assert len(FORM_S3_ITEMS) == 17
    assert "early_items" in FORM_S3_DERIVED
    assert "late_items" in FORM_S3_DERIVED
    assert "ITEM 1" in FORM_S3_DERIVED["early_items"]
    assert "ITEM 16" in FORM_S3_DERIVED["late_items"]
    item_map = {item.item: item for item in FORM_S3_ITEMS}
    assert "ITEM 13" not in item_map
    assert "ITEM 12" in item_map
    assert "ITEM 14" in item_map


def test_form_s4_taxonomy_and_derived() -> None:
    assert len(FORM_S4_ITEMS) == 22
    assert "early_items" in FORM_S4_DERIVED
    assert "late_items" in FORM_S4_DERIVED
    assert "ITEM 1" in FORM_S4_DERIVED["early_items"]
    assert "ITEM 21" in FORM_S4_DERIVED["late_items"]
    item_map = {item.item: item for item in FORM_S4_ITEMS}
    assert "ITEM 4" in item_map
    assert "the merger" in item_map["ITEM 4"].names
    assert "ITEM 22" in item_map


def test_form_s8_taxonomy_and_derived() -> None:
    assert len(FORM_S8_ITEMS) == 9
    assert "early_items" in FORM_S8_DERIVED
    assert "late_items" in FORM_S8_DERIVED
    assert "ITEM 1" in FORM_S8_DERIVED["early_items"]
    assert "ITEM 8" in FORM_S8_DERIVED["late_items"]
    item_map = {item.item: item for item in FORM_S8_ITEMS}
    assert "plan information" in item_map["ITEM 1"].names
    assert "undertakings" in item_map["ITEM 9"].names
