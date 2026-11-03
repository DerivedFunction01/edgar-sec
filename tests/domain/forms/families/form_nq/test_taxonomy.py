"""Tests for the N-Q taxonomy specifications."""

from edgar_sec.domain.forms.families.form_nq.taxonomy import FORM_NQ_ITEMS


def test_taxonomy_items() -> None:
    """The taxonomy carries specimen-evidenced items in order."""
    assert FORM_NQ_ITEMS
    assert all(item.names for item in FORM_NQ_ITEMS)
    assert FORM_NQ_ITEMS[0].early is True
