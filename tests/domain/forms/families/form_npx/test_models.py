"""Tests for Form N-PX document models."""

from edgar_sec.domain.forms.families.form_npx.models import (
    FormNPxDocument,
    ProxyVoteRow,
)


def test_proxy_vote_row_defaults() -> None:
    """Optional vote row fields default to None and tuples to empty."""
    row = ProxyVoteRow(
        issuer_name="ACME CORP",
        meeting_date="06/12/2025",
        vote_description="Election of directors",
    )
    assert row.cusip is None
    assert row.category_types == ()
    assert row.how_voted == ()


def test_npx_document_rows() -> None:
    """Document carries cover metadata and the vote rows tuple."""
    row = ProxyVoteRow(
        issuer_name="ACME CORP",
        meeting_date="06/12/2025",
        vote_description="Election of directors",
        cusip="001000000",
        how_voted=("For",),
    )
    doc = FormNPxDocument(
        submission_type="N-PX",
        vote_rows=(row,),
        registrant_type="RMIC",
        report_type="FUND VOTING REPORT",
    )
    assert doc.vote_rows == (row,)
    assert doc.registrant_type == "RMIC"
