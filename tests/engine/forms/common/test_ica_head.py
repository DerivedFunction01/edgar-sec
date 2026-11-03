"""Tests for the shared ICA cover-head extraction."""

from edgar_sec.engine.forms.common.ica_head import ica_cover_fields

_LINES = [
    "UNITED STATES SECURITIES AND EXCHANGE COMMISSION",
    "FORM N-CSR",
    "Investment Company Act file number  811-06495",
    "Flaherty & Crumrine Preferred Income Opportunity Fund Incorporated",
    "(Exact name of registrant as specified in charter)",
    "For the semi-annual period ended May 31, 2018",
]


def test_ica_cover_fields() -> None:
    """File number, registrant name, and period extract from a cover."""
    fields = ica_cover_fields(_LINES)
    assert fields["file_number"] == "811-06495"
    assert fields["registrant_name"].startswith("Flaherty & Crumrine")
    assert fields["report_period"] == "May 31, 2018"


def test_ica_cover_fields_missing() -> None:
    """An empty cover yields honest absence, never invented values."""
    fields = ica_cover_fields(["Some body text without a cover"])
    assert fields["file_number"] is None
    assert fields["registrant_name"] is None
    assert fields["report_period"] is None
