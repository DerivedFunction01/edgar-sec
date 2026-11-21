"""Tests for the 18-K taxonomy specifications."""

from edgar_sec.domain.forms.families.form_18k.taxonomy import FORM_18K_ITEMS


def test_taxonomy_items() -> None:
    """The taxonomy carries specimen-evidenced items in order."""
    assert FORM_18K_ITEMS
    assert all(item.names for item in FORM_18K_ITEMS)
    assert FORM_18K_ITEMS[0].early is True
