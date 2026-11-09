"""Unit tests for in-memory PyArrow table builders."""

from pathlib import Path
import pyarrow as pa

from edgar_sec.apps.client.tables import (
    build_catalog_table,
    build_exhibits_table,
    build_index_table,
    build_joined_table,
    build_linkbases_table,
    build_payload_table,
)
from edgar_sec.domain.document.aggregate import (
    FilingAggregate,
    FilingAttachment,
    is_exhibit_attachment,
)
from edgar_sec.domain.identity import AccessionNumber, Cik


def _sample_filing(tmp_path: Path) -> FilingAggregate:
    p = tmp_path / "primary.htm"
    p.write_bytes(b"content")
    acc = AccessionNumber.from_any("0000320193-23-000106")
    cik = Cik.from_raw(320193)
    att = FilingAttachment(
        attachment_id="entry-abc",
        document_type="EX-10.1",
        filename="ex10_1.htm",
        url="http://sec.gov/ex10_1.htm",
        size=100,
        sequence=7,
    )
    return FilingAggregate(
        accession=acc,
        primary_cik=cik,
        ciks=(cik,),
        form="10-K",
        filing_date="2023-11-03",
        report_date="2023-09-30",
        primary_document_path="primary.htm",
        primary_storage_path=p,
        attachments=(att,),
    )


def test_is_exhibit_attachment() -> None:
    assert is_exhibit_attachment("EX-10.1", "doc.htm") is True
    assert is_exhibit_attachment("10-K", "report.htm") is False


def test_build_index_table_sequence_fallback(tmp_path: Path) -> None:
    filing = _sample_filing(tmp_path)
    att = filing.attachments[0]
    unsequenced = FilingAttachment(
        attachment_id=att.attachment_id,
        document_type=att.document_type,
        filename=att.filename,
        url=att.url,
        size=att.size,
    )
    bare = FilingAggregate(
        accession=filing.accession,
        primary_cik=filing.primary_cik,
        ciks=filing.ciks,
        form=filing.form,
        filing_date=filing.filing_date,
        attachments=(unsequenced,),
    )
    idx = build_index_table([bare])
    assert idx["sequence"][0].as_py() == 1


def test_build_tables(tmp_path: Path) -> None:
    filings = [_sample_filing(tmp_path)]
    cat = build_catalog_table(filings)
    assert isinstance(cat, pa.Table)
    assert cat.num_rows == 1
    assert cat["accession"][0].as_py() == "0000320193-23-000106"

    idx = build_index_table(filings)
    assert isinstance(idx, pa.Table)
    assert idx.num_rows == 1
    assert idx["sequence"][0].as_py() == 7

    ex = build_exhibits_table(filings)
    assert isinstance(ex, pa.Table)
    assert ex.num_rows == 1

    lb = build_linkbases_table(filings)
    assert isinstance(lb, pa.Table)

    pay = build_payload_table(filings)
    assert isinstance(pay, pa.Table)
    assert pay.num_rows == 1

    jnd = build_joined_table(filings)
    assert isinstance(jnd, pa.Table)
    assert jnd.num_rows == 1


def test_build_index_table_roles(tmp_path: Path) -> None:
    filing = _sample_filing(tmp_path)
    primary = FilingAttachment(
        attachment_id="entry-primary",
        document_type="10-K",
        filename="primary.htm",
        url="http://sec.gov/primary.htm",
        sequence=1,
    )
    combined = FilingAggregate(
        accession=filing.accession,
        primary_cik=filing.primary_cik,
        ciks=filing.ciks,
        form=filing.form,
        filing_date=filing.filing_date,
        attachments=(primary, *filing.attachments),
    )
    idx = build_index_table([combined])
    roles = {row["filename"]: row["role"] for row in idx.to_pylist()}
    assert roles == {"primary.htm": "primary", "ex10_1.htm": "exhibit"}
    ex = build_exhibits_table([combined])
    assert [row["role"] for row in ex.to_pylist()] == ["exhibit"]


def test_build_linkbases_table_classifies_from_row_fields() -> None:
    atts = (
        FilingAttachment(
            attachment_id="d",
            document_type="10-K",
            filename="doc.htm",
            url="http://sec.gov/doc.htm",
            description="Calculation Linkbase",
        ),
        FilingAttachment(
            attachment_id="i",
            document_type="EX-102.INS",
            filename="inst.xml",
            url="http://sec.gov/inst.xml",
        ),
        FilingAttachment(
            attachment_id="b",
            document_type="EX-101",
            filename="bare.xml",
            url="http://sec.gov/bare.xml",
        ),
    )
    filing = FilingAggregate(
        accession=AccessionNumber.from_any("0000320193-23-000106"),
        primary_cik=Cik.from_raw(320193),
        ciks=(Cik.from_raw(320193),),
        form="10-K",
        filing_date="2023-11-03",
        attachments=atts,
    )
    lb = build_linkbases_table([filing])
    found = {row["filename"]: row["linkbase_type"] for row in lb.to_pylist()}
    assert found == {"doc.htm": "calculation", "inst.xml": "instance"}


def test_build_payload_table_no_fabricated_target(tmp_path: Path) -> None:
    filing = _sample_filing(tmp_path)
    pay = build_payload_table([filing])
    row = pay.to_pylist()[0]
    assert row["target_id"] == ""
    assert row["outcome"] == "acquired"
    assert row["attempt_count"] == 0

    bare = FilingAggregate(
        accession=filing.accession,
        primary_cik=filing.primary_cik,
        ciks=filing.ciks,
        form=filing.form,
        filing_date=filing.filing_date,
    )
    planned = build_payload_table([bare]).to_pylist()[0]
    assert planned["outcome"] == "planned"
    assert planned["target_id"] == ""

    fetched_only = FilingAggregate(
        accession=filing.accession,
        primary_cik=filing.primary_cik,
        ciks=filing.ciks,
        form=filing.form,
        filing_date=filing.filing_date,
        fetcher=lambda f: b"content",
    )
    assert build_payload_table([fetched_only]).to_pylist()[0]["outcome"] == "planned"
