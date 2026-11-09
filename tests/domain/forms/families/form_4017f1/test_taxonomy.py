"""Tests for the 40-17F1 taxonomy specifications."""

from edgar_sec.domain.forms.families.form_4017f1.taxonomy import FORM_4017F1_ITEMS


def test_taxonomy_items() -> None:
    """The taxonomy carries specimen-evidenced items in order."""
    assert FORM_4017F1_ITEMS
    assert all(item.names for item in FORM_4017F1_ITEMS)
    assert FORM_4017F1_ITEMS[0].item == "INSTRUCTIONS"
