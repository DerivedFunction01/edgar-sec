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
    is_exhibit_attachment,
)
from edgar_sec.domain.document.aggregate import FilingAggregate, FilingAttachment
from edgar_sec.domain.identity import AccessionNumber, Cik


def _sample_filing(tmp_path: Path) -> FilingAggregate:
    p = tmp_path / "primary.htm"
    p.write_bytes(b"content")
    acc = AccessionNumber.from_any("0000320193-23-000106")
    cik = Cik.from_raw(320193)
    att = FilingAttachment(
        attachment_id="1",
        document_type="EX-10.1",
        filename="ex10_1.htm",
        url="http://sec.gov/ex10_1.htm",
        size=100,
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


def test_build_tables(tmp_path: Path) -> None:
    filings = [_sample_filing(tmp_path)]
    cat = build_catalog_table(filings)
    assert isinstance(cat, pa.Table)
    assert cat.num_rows == 1
    assert cat["accession"][0].as_py() == "0000320193-23-000106"

    idx = build_index_table(filings)
    assert isinstance(idx, pa.Table)
    assert idx.num_rows == 1

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
