"""Tests for annual report item taxonomies (10-K, 20-F)."""

from __future__ import annotations

from edgar_sec.domain.forms.families.annual.taxonomy import (
    FORM_10K_DERIVED,
    FORM_10K_ITEMS,
    FORM_20F_DERIVED,
    FORM_20F_ITEMS,
    ITEMS,
    PARTS,
)


def test_form_10k_taxonomy_items() -> None:
    assert len(FORM_10K_ITEMS) > 15
    assert len(PARTS) == 4
    assert "ITEM 1" in ITEMS
    assert "ITEM 7" in ITEMS
    assert "ITEM 8" in ITEMS


def test_form_20f_taxonomy_items() -> None:
    assert len(FORM_20F_ITEMS) > 15


def test_form_10k_derived_lookups() -> None:
    assert "early_items" in FORM_10K_DERIVED
    assert "late_items" in FORM_10K_DERIVED
    assert "matcher" in FORM_10K_DERIVED
    assert "ITEM 1" in FORM_10K_DERIVED["early_items"]
    assert "ITEM 8" in FORM_10K_DERIVED["late_items"]
    assert FORM_10K_DERIVED["late_item_re"].search("ITEM 8 Financial Statements")


def test_form_20f_derived_lookups() -> None:
    assert "early_items" in FORM_20F_DERIVED
    assert "late_items" in FORM_20F_DERIVED
    assert "matcher" in FORM_20F_DERIVED
