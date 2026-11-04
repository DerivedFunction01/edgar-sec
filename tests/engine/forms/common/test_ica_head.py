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


def test_ica_reporting_period_caption() -> None:
    """The facing sheet's reporting-period caption carries the period."""
    fields = ica_cover_fields(
        [
            "FORM N-CSR",
            "Date of fiscal year end: April 30",
            "Date of reporting period: April 30, 2018",
        ]
    )
    assert fields["report_period"] == "April 30, 2018"


def test_ica_reporting_period_numeric_caption() -> None:
    """Numeric caption dates resolve in their filed form."""
    fields = ica_cover_fields(["FORM N-Q", "Date of reporting period: 09/30/11"])
    assert fields["report_period"] == "09/30/11"


def test_ica_period_caption_beats_ended_prose() -> None:
    """The caption wins over an earlier "ended" mention in head prose."""
    fields = ica_cover_fields(
        [
            "For the period ended May 31, 2017, the fund filed an amendment.",
            "Date of reporting period: April 30, 2018",
        ]
    )
    assert fields["report_period"] == "April 30, 2018"


def test_ica_period_caption_range_resolves_to_end() -> None:
    """A caption naming a range resolves to the period end."""
    fields = ica_cover_fields(
        ["Date of reporting period:  October 1, 2003 to March 31, 2004"]
    )
    assert fields["report_period"] == "March 31, 2004"


def test_ica_file_number_caption_variants() -> None:
    """Print variants of the file-number caption and number resolve."""
    fields = ica_cover_fields(["File No. 811\u201123493"])
    assert fields["file_number"] == "811-23493"
    fields = ica_cover_fields(["Investment Company Act File Number: 811- 4173"])
    assert fields["file_number"] == "811-4173"


def test_ica_registrant_name_blank_doubled_lookback() -> None:
    """Blanks and the file-number line do not consume the name horizon."""
    fields = ica_cover_fields(
        [
            "FORM N-CSR",
            "",
            "Wells Fargo Income Opportunities Fund",
            "",
            "Investment Company Act file number: 811-21269",
            "",
            "(Exact name of registrant as specified in charter)",
        ]
    )
    assert fields["registrant_name"] == "Wells Fargo Income Opportunities Fund"
    assert fields["file_number"] == "811-21269"
