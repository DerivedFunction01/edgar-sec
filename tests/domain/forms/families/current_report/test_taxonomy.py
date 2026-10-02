"""Tests for current report item taxonomy (8-K)."""

from __future__ import annotations

from edgar_sec.domain.forms.families.current_report.taxonomy import (
    FORM_8K_DERIVED,
    FORM_8K_ITEMS,
    ITEMS,
    PARTS,
)


def test_form_8k_taxonomy_items() -> None:
    assert len(FORM_8K_ITEMS) > 5
    assert len(PARTS) == 0
    assert "ITEM 1.01" in ITEMS
    assert "ITEM 2.01" in ITEMS


def test_form_8k_derived_lookups() -> None:
    assert "early_items" in FORM_8K_DERIVED
    assert "late_items" in FORM_8K_DERIVED
    assert "matcher" in FORM_8K_DERIVED
    assert "ITEM 1.01" in FORM_8K_DERIVED["late_items"]
    assert FORM_8K_DERIVED["late_item_re"].search("ITEM 1.01 Entry into Material")
