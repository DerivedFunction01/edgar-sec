"""Tests for the N-VP taxonomy specifications."""

from edgar_sec.domain.forms.families.form_nvp.taxonomy import FORM_NVP_ITEMS


def test_taxonomy_items() -> None:
    """The taxonomy carries specimen-evidenced items in order."""
    assert FORM_NVP_ITEMS
    assert all(item.names for item in FORM_NVP_ITEMS)
    assert FORM_NVP_ITEMS[0].early is True
    items = [item.item for item in FORM_NVP_ITEMS]
    assert items.index("FEES AND EXPENSES") < items.index("RISKS")
    assert items.index("NOTES TO FINANCIAL STATEMENTS") < items.index(
        "APPENDIX: PORTFOLIOS AVAILABLE"
    )
