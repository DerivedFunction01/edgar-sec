"""Tests for the S-6 taxonomy specifications."""

from edgar_sec.domain.forms.families.form_s6.taxonomy import FORM_S6_ITEMS


def test_taxonomy_items() -> None:
    """The taxonomy carries specimen-evidenced items in order."""
    assert FORM_S6_ITEMS
    assert all(item.names for item in FORM_S6_ITEMS)
    assert FORM_S6_ITEMS[0].item == "SUMMARY OF ESSENTIAL INFORMATION"
    assert FORM_S6_ITEMS[0].early is True
    assert FORM_S6_ITEMS[-1].item == "EXHIBIT INDEX"
