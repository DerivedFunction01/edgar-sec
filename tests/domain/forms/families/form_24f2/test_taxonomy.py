"""Tests for the 24F-2 taxonomy specifications."""

from edgar_sec.domain.forms.families.form_24f2.taxonomy import FORM_24F2_ITEMS


def test_taxonomy_items() -> None:
    """The taxonomy carries specimen-evidenced items in order."""
    assert FORM_24F2_ITEMS
    assert all(item.names for item in FORM_24F2_ITEMS)
    assert FORM_24F2_ITEMS[0].early is True
