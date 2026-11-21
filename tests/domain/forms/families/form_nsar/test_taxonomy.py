"""Tests for the NSAR taxonomy specifications."""

from edgar_sec.domain.forms.families.form_nsar.taxonomy import FORM_NSAR_ITEMS


def test_taxonomy_items() -> None:
    """The taxonomy carries specimen-evidenced items in order."""
    assert FORM_NSAR_ITEMS
    assert all(item.names for item in FORM_NSAR_ITEMS)
    assert FORM_NSAR_ITEMS[0].early is True
