"""Tests for the 40-17F2 taxonomy specifications."""

from edgar_sec.domain.forms.families.form_4017f2.taxonomy import FORM_4017F2_ITEMS


def test_taxonomy_items() -> None:
    """The taxonomy carries specimen-evidenced items in order."""
    assert FORM_4017F2_ITEMS
    assert all(item.names for item in FORM_4017F2_ITEMS)
    assert FORM_4017F2_ITEMS[0].item == "INSTRUCTIONS"
