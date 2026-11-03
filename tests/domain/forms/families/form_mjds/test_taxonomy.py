from __future__ import annotations

from edgar_sec.domain.forms.families.form_mjds.taxonomy import (
    FORM_F7_ITEMS,
    FORM_F8_ITEMS,
    FORM_F9_ITEMS,
    FORM_F10_AMENDMENT_VARIANT_ITEMS,
    FORM_F10_ITEMS,
    FORM_F80_ITEMS,
    MJDS_LEGENDS_ITEMS,
    MJDS_UNDERTAKINGS_ITEMS,
)


def test_legends_tail_items() -> None:
    keys = [(d.item, d.part) for d in MJDS_LEGENDS_ITEMS]
    assert keys == [("ITEM 1", 2), ("ITEM 2", 2), ("ITEM 3", 2), ("ITEM 4", 2)]
    by_item = {d.item: d.names for d in MJDS_LEGENDS_ITEMS}
    assert "home jurisdiction document(s)" in by_item["ITEM 1"]
    assert by_item["ITEM 2"] == ("informational legends", "informational legend")
    assert by_item["ITEM 3"] == ("incorporation of certain information by reference",)
    assert by_item["ITEM 4"] == ("list of documents filed",)


def test_undertakings_tail_items() -> None:
    by_item = {d.item: d.names for d in MJDS_UNDERTAKINGS_ITEMS}
    assert "undertakings" in by_item["ITEM 1"]
    assert by_item["ITEM 2"] == ("consent to service of process",)


def test_per_form_tail_assignment() -> None:
    assert FORM_F7_ITEMS == MJDS_LEGENDS_ITEMS
    assert FORM_F9_ITEMS == MJDS_UNDERTAKINGS_ITEMS
    assert FORM_F10_ITEMS == MJDS_UNDERTAKINGS_ITEMS
    assert FORM_F8_ITEMS == (*MJDS_LEGENDS_ITEMS, *MJDS_UNDERTAKINGS_ITEMS)
    assert FORM_F80_ITEMS == FORM_F8_ITEMS


def test_f10_amendment_variant_is_a_record_not_a_taxonomy() -> None:
    keys = [d.item for d in FORM_F10_AMENDMENT_VARIANT_ITEMS]
    assert keys == ["ITEM 8", "ITEM 9", "ITEM 10"]
    for definition in FORM_F10_AMENDMENT_VARIANT_ITEMS:
        assert definition.optional is True
        assert definition.part == 2
    assert FORM_F10_AMENDMENT_VARIANT_ITEMS not in (
        FORM_F7_ITEMS,
        FORM_F10_ITEMS,
    )
