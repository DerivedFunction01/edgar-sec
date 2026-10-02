"""Tests for quarterly report item taxonomy (10-Q)."""

from __future__ import annotations

from edgar_sec.domain.forms.families.quarterly.taxonomy import (
    FORM_10Q_DERIVED,
    FORM_10Q_ITEMS,
    ITEMS,
    PARTS,
)


def test_form_10q_taxonomy_items() -> None:
    assert len(FORM_10Q_ITEMS) > 5
    assert len(PARTS) == 2
    assert "ITEM 1" in ITEMS
    assert "ITEM 2" in ITEMS


def test_form_10q_derived_lookups() -> None:
    assert "early_items" in FORM_10Q_DERIVED
    assert "late_items" in FORM_10Q_DERIVED
    assert "matcher" in FORM_10Q_DERIVED
    assert "ITEM 1" in FORM_10Q_DERIVED["early_items"]
    assert FORM_10Q_DERIVED["late_item_re"].search("ITEM 6 Exhibits")
