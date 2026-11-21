"""Tests for the N-CSR taxonomy specifications."""

from edgar_sec.domain.forms.families.form_ncsr.taxonomy import FORM_NCSR_ITEMS


def test_taxonomy_items() -> None:
    """The taxonomy carries specimen-evidenced items in order."""
    assert FORM_NCSR_ITEMS
    assert all(item.names for item in FORM_NCSR_ITEMS)
    assert FORM_NCSR_ITEMS[0].early is True
