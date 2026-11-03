"""Tests for Form N-MFP document models."""

from edgar_sec.domain.forms.families.form_nmfp.models import (
    FormNMfpDocument,
    NMfpSecurity,
)


def test_nmfp_security_defaults() -> None:
    """Optional security fields default to None."""
    row = NMfpSecurity(issuer_name="US TREASURY", title="T-BILL", cusip="912797PU5")
    assert row.isin is None
    assert row.percent_of_net_assets is None


def test_nmfp_document_rows() -> None:
    """Document carries series identity and the securities tuple."""
    row = NMfpSecurity(
        issuer_name="US TREASURY",
        title="T-BILL",
        cusip="912797PU5",
        value_including_support="9000.00",
    )
    doc = FormNMfpDocument(
        submission_type="N-MFP3",
        securities=(row,),
        generation=3,
        series_name="ACME GOVERNMENT FUND",
        report_date="2025-06-30",
    )
    assert doc.securities == (row,)
    assert doc.generation == 3
