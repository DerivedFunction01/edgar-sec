"""Tests for the N-30D taxonomy specifications."""

from edgar_sec.domain.forms.families.form_n30d.taxonomy import FORM_N30D_ITEMS


def test_taxonomy_items() -> None:
    """The taxonomy carries specimen-evidenced items in order."""
    assert FORM_N30D_ITEMS
    assert all(item.names for item in FORM_N30D_ITEMS)
    assert FORM_N30D_ITEMS[0].early is True
