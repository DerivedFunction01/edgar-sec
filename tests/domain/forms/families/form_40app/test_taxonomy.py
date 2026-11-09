"""Tests for the 40-APP taxonomy specifications."""

from edgar_sec.domain.forms.families.form_40app.taxonomy import FORM_40APP_ITEMS


def test_taxonomy_items() -> None:
    """The taxonomy carries specimen-evidenced items in order."""
    assert FORM_40APP_ITEMS
    assert all(item.names for item in FORM_40APP_ITEMS)
    assert FORM_40APP_ITEMS[0].early is True
