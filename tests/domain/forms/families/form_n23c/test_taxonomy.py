"""Tests for the N-23C notice family taxonomy specifications."""

from edgar_sec.domain.forms.families.form_n23c.taxonomy import (
    FORM_N23C1_ITEMS,
    FORM_N23C2_ITEMS,
    FORM_N23C3_ITEMS,
)


def test_taxonomy_items() -> None:
    """The taxonomies carry specimen-evidenced items in order."""
    for items in (FORM_N23C1_ITEMS, FORM_N23C2_ITEMS, FORM_N23C3_ITEMS):
        assert items
        assert all(item.names for item in items)
    assert FORM_N23C1_ITEMS[0].early is True
    assert FORM_N23C3_ITEMS[0].early is True
    assert FORM_N23C2_ITEMS[-1].item == "SIGNATURES"
    assert FORM_N23C3_ITEMS[-1].item == "SIGNATURES"
