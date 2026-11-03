"""Tests for the 497 taxonomy specifications."""

from edgar_sec.domain.forms.families.form_497.taxonomy import FORM_497_ITEMS


def test_taxonomy_items() -> None:
    """The taxonomy carries specimen-evidenced items in order."""
    assert FORM_497_ITEMS
    assert all(item.names for item in FORM_497_ITEMS)
    assert FORM_497_ITEMS[0].early is True
