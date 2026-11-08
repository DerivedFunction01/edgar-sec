from __future__ import annotations

from edgar_sec.domain.forms.families.current.taxonomy import (
    FORM_8K_DERIVED,
    FORM_8K_ITEMS,
    ITEMS,
    PARTS,
    uses_ifrs_headline_vocabulary,
)


def test_form_8k_taxonomy_items() -> None:
    assert len(FORM_8K_ITEMS) > 5
    assert len(PARTS) == 0
    assert "ITEM 1.01" in ITEMS
    assert "ITEM 2.01" in ITEMS


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
