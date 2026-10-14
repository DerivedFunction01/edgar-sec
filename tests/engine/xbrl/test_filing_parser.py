"""Unit tests for parse_filing_xbrl orchestrator."""

from tests.support import fixture_path
from edgar_sec.domain.document.aggregate import (
    FilingAggregate,
    FilingAttachment,
)
from edgar_sec.domain.identity import AccessionNumber, Cik
from edgar_sec.engine.xbrl.filing_parser import parse_filing_xbrl


def test_parse_filing_xbrl_from_attachments() -> None:
    """Verify parse_filing_xbrl parses all linkbases and facts on an aggregate."""
    cal_bytes = fixture_path("xbrl/msft-20240630_cal.xml").read_bytes()
    pre_bytes = fixture_path("xbrl/msft-20240630_pre.xml").read_bytes()
    lab_bytes = fixture_path("xbrl/msft-20240630_lab.xml").read_bytes()
    xsd_bytes = fixture_path("xbrl/msft-20240630.xsd").read_bytes()
    htm_bytes = fixture_path("xbrl/msft-20240630_htm.xml").read_bytes()

    acc = AccessionNumber("0000950170-24-087843")
    cik = Cik.from_raw(789019)

    attachments = (
        FilingAttachment(
            attachment_id=f"{acc}-cal",
            document_type="EX-101.CAL",
            filename="msft-20240630_cal.xml",
            url="https://sec.gov/cal.xml",
            fetcher=lambda _: cal_bytes,
        ),
        FilingAttachment(
            attachment_id=f"{acc}-pre",
            document_type="EX-101.PRE",
            filename="msft-20240630_pre.xml",
            url="https://sec.gov/pre.xml",
            fetcher=lambda _: pre_bytes,
        ),
        FilingAttachment(
            attachment_id=f"{acc}-lab",
            document_type="EX-101.LAB",
            filename="msft-20240630_lab.xml",
            url="https://sec.gov/lab.xml",
            fetcher=lambda _: lab_bytes,
        ),
        FilingAttachment(
            attachment_id=f"{acc}-sch",
            document_type="EX-101.SCH",
            filename="msft-20240630.xsd",
            url="https://sec.gov/sch.xsd",
            fetcher=lambda _: xsd_bytes,
        ),
        FilingAttachment(
            attachment_id=f"{acc}-ins",
            document_type="XML",
            filename="msft-20240630_htm.xml",
            url="https://sec.gov/ins.xml",
            fetcher=lambda _: htm_bytes,
        ),
    )

    filing = FilingAggregate(
        accession=acc,
        primary_cik=cik,
        ciks=(cik,),
        form="10-K",
        filing_date="2024-07-30",
        attachments=attachments,
    )

    xbrl = parse_filing_xbrl(filing)
    assert xbrl.accession == acc
    assert xbrl.cik == cik
    assert len(xbrl.linkbases.calculation_arcs) == 4
    assert len(xbrl.linkbases.presentation_arcs) == 2
    assert len(xbrl.linkbases.labels) == 2
    assert len(xbrl.linkbases.declarations) == 2
    assert len(xbrl.facts) == 8
