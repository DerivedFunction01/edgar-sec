"""Tests for the 40-17G taxonomy specifications."""

from edgar_sec.domain.forms.families.form_4017g.taxonomy import FORM_4017G_ITEMS


def test_taxonomy_items() -> None:
    """The taxonomy carries specimen-evidenced items in order."""
    assert FORM_4017G_ITEMS
    assert all(item.names for item in FORM_4017G_ITEMS)
    assert FORM_4017G_ITEMS[0].item == "DECLARATIONS"
