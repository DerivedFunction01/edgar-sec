"""Tests for Form N-CEN document models."""

from edgar_sec.domain.forms.families.form_ncen.models import FormNCenDocument


def test_ncen_document_defaults() -> None:
    """Optional identity fields default to None and counts to zero."""
    doc = FormNCenDocument(
        submission_type="N-CEN",
        registrant_name="ACME FUND",
        directors=(),
    )
    assert doc.file_number is None
    assert doc.series_count == 0
    assert doc.custodian_count == 0


def test_ncen_document_directors() -> None:
    """Document carries the director name tuple and identity core."""
    doc = FormNCenDocument(
        submission_type="N-CEN/A",
        registrant_name="ACME FUND",
        directors=("JANE DOE", "JOHN ROE"),
        file_number="811-00000",
        registrant_cik="0000123456",
        classification_type="N-2",
    )
    assert doc.directors == ("JANE DOE", "JOHN ROE")
    assert doc.classification_type == "N-2"
