from __future__ import annotations

from edgar_sec.domain.forms.families.current.taxonomy import (
    FORM_6K_DERIVED,
    FORM_6K_ITEMS,
    FORM_8K_DERIVED,
    FORM_8K_ITEMS,
    ITEMS,
    ITEMS_6K,
    PARTS,
    uses_ifrs_headline_vocabulary,
)


def test_form_8k_taxonomy_items() -> None:
    assert len(FORM_8K_ITEMS) > 5
    assert len(PARTS) == 0
    assert "ITEM 1.01" in ITEMS
    assert "ITEM 2.01" in ITEMS


def test_form_6k_taxonomy_is_its_own_item_set() -> None:
    assert [d.item for d in FORM_6K_ITEMS] == ["PRESS RELEASE"]
    assert ITEMS_6K == {"PRESS RELEASE": "press release"}
    assert not {d.item for d in FORM_6K_ITEMS} & {d.item for d in FORM_8K_ITEMS}
    names = {name for d in FORM_6K_ITEMS for name in d.names}
    assert names == {"press release", "for immediate release"}


def test_form_6k_derived_lookups() -> None:
    assert "PRESS RELEASE" in FORM_6K_DERIVED["late_items"]
    assert "matcher" in FORM_6K_DERIVED


def test_ifrs_headline_vocabulary_forms() -> None:
    assert uses_ifrs_headline_vocabulary("6-K")
    assert uses_ifrs_headline_vocabulary("6-K/A")
    assert not uses_ifrs_headline_vocabulary("8-K")
    assert not uses_ifrs_headline_vocabulary("8-K/A")


def test_form_8k_derived_lookups() -> None:
    assert "early_items" in FORM_8K_DERIVED
    assert "late_items" in FORM_8K_DERIVED
    assert "matcher" in FORM_8K_DERIVED
    assert "ITEM 1.01" in FORM_8K_DERIVED["late_items"]
    assert FORM_8K_DERIVED["late_item_re"].search("ITEM 1.01 Entry into Material")
