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


def test_filing_attachment_graphics_and_fetcher(tmp_path: Path) -> None:
    graphic = FilingAttachment(
        attachment_id="img-1",
        document_type="GRAPHIC",
        filename="chart.png",
        url="https://sec.gov/chart.png",
        fetcher=lambda _a: b"\x89PNG\r\n\x1a\n",
    )
    assert graphic.is_graphic
    assert not graphic.is_xml
    assert graphic.raw() == b"\x89PNG\r\n\x1a\n"
    assert graphic.text() is None

    dest = tmp_path / "saved_chart.png"
    graphic.save(dest)
    assert dest.read_bytes() == b"\x89PNG\r\n\x1a\n"


def test_filing_aggregate_non_standard_accessors(tmp_path: Path) -> None:
    accession = AccessionNumber.from_any("0000320193-25-000079")
    filing = FilingAggregate(
        accession=accession,
        primary_cik=Cik(320193),
        ciks=(Cik(320193),),
        form="10-K",
        filing_date="2025-10-31",
        bundle_fetcher=lambda _f: b"SGML SUBMISSION BUNDLE",
        index_fetcher=lambda _f: "<html><head><title>Index</title></head></html>",
        document_opener=lambda _f, name: f"content of {name}".encode("utf-8"),
        renderer=lambda _f: "NORMALIZED 10-K TEXT",
    )

    assert filing.full_submission_bundle() == b"SGML SUBMISSION BUNDLE"
    dest_bundle = tmp_path / "bundle.txt"
    filing.save_bundle(dest_bundle)
    assert dest_bundle.read_bytes() == b"SGML SUBMISSION BUNDLE"

    assert "<title>Index</title>" in filing.index_page()
    assert filing.open_document("subsidiaries.htm") == b"content of subsidiaries.htm"
    assert filing.render() == "NORMALIZED 10-K TEXT"
    assert filing.as_report().text() == "NORMALIZED 10-K TEXT"


def test_filing_aggregate_payload_metadata() -> None:
    filing_form4 = FilingAggregate(
        accession=AccessionNumber.from_any("0001181431-05-056000"),
        primary_cik=Cik(109694),
        ciks=(Cik(109694),),
        form="4",
        filing_date="2005-09-15",
        primary_document_path="xslF345X01/form4.xml",
    )
    assert filing_form4.raw_format == "xml"
    assert filing_form4.raw_content_type == "text/xml"
    assert filing_form4.render_format == "xml"
    assert filing_form4.render_operation == "render_to_xml"

    filing_legacy = FilingAggregate(
        accession=AccessionNumber.from_any("0000950123-01-000001"),
        primary_cik=Cik(100),
        ciks=(Cik(100),),
        form="4",
        filing_date="2001-01-01",
        primary_document_path="form4.htm",
    )
    assert filing_legacy.raw_format == "htm"
    assert filing_legacy.raw_content_type == "text/html"
    assert filing_legacy.render_format == "xml"
    assert filing_legacy.render_operation == "render_to_xml"


def test_filing_attachment_payload_metadata() -> None:
    attachment = FilingAttachment(
        attachment_id="att-pdf",
        document_type="EX-99.1",
        filename="presentation.pdf",
        url="https://sec.gov/ex99.pdf",
    )
    assert attachment.raw_format == "pdf"
    assert attachment.raw_content_type == "application/pdf"
    assert attachment.render_format == "pdf"
    assert attachment.raw_metadata.is_binary
