"""Tests for filing submission aggregate domain models."""

from __future__ import annotations

from pathlib import Path

from edgar_sec.domain.document.aggregate import FilingAggregate, FilingAttachment
from edgar_sec.domain.identity import AccessionNumber, Cik


def test_filing_aggregate_tracks_identity_and_joint_filers() -> None:
    accession = AccessionNumber.from_any("0001181431-05-056000")
    primary_cik = Cik(109694)
    ciks = (primary_cik, Cik(1067983), Cik(820027))

    filing = FilingAggregate(
        accession=accession,
        primary_cik=primary_cik,
        ciks=ciks,
        form="4",
        filing_date="2005-09-15",
    )

    assert filing.is_joint_filing
    assert filing.has_cik(109694)
    assert filing.has_cik("0001067983")
    assert not filing.has_cik(999999)


def test_filing_attachment_exhibits_filtering() -> None:
    accession = AccessionNumber.from_any("0000320193-23-000106")
    exhibit = FilingAttachment(
        attachment_id="att-1",
        document_type="EX-21",
        filename="subsidiaries.htm",
        url="https://sec.gov/ex21.htm",
    )
    doc = FilingAttachment(
        attachment_id="att-2",
        document_type="10-K",
        filename="primary.htm",
        url="https://sec.gov/10k.htm",
    )
    filing = FilingAggregate(
        accession=accession,
        primary_cik=Cik(320193),
        ciks=(Cik(320193),),
        form="10-K",
        filing_date="2023-11-03",
        attachments=(exhibit, doc),
    )

    assert not filing.is_joint_filing
    assert len(filing.exhibits) == 1
    assert filing.exhibits[0].document_type == "EX-21"
