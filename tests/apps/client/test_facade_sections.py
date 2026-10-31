"""Unit tests for client facade section and note extraction and tables."""

from pathlib import Path

import pyarrow as pa
import pytest

from edgar_sec.apps.client.facade import Edgar
from edgar_sec.apps.client.models import FilingsResult
from edgar_sec.apps.client.tables import (
    build_catalog_table,
    build_notes_table,
    build_sections_table,
)
from edgar_sec.domain.document.aggregate import FilingAggregate
from edgar_sec.domain.identity import AccessionNumber, Cik


def _sample_10k_filing(tmp_path: Path) -> FilingAggregate:
    sample_text = (
        "PART I\n"
        "ITEM 1. BUSINESS\n"
        "The business overview.\n"
        "ITEM 1A. RISK FACTORS\n"
        "General risks.\n"
        "PART II\n"
        "ITEM 7. MANAGEMENT'S DISCUSSION AND ANALYSIS\n"
        "MD&A discussion.\n"
        "ITEM 8. FINANCIAL STATEMENTS AND SUPPLEMENTARY DATA\n"
        "NOTES TO CONSOLIDATED FINANCIAL STATEMENTS\n"
        "Note 1. Summary of Significant Accounting Policies\n"
        "Accounting details.\n"
        "Note 2. Revenue Recognition\n"
        "Revenue details.\n"
    )
    p = tmp_path / "10k_primary.txt"
    p.write_text(sample_text, encoding="utf-8")
    acc = AccessionNumber.from_any("0000320193-23-000106")
    cik = Cik.from_raw(320193)
    return FilingAggregate(
        accession=acc,
        primary_cik=cik,
        ciks=(cik,),
        form="10-K",
        filing_date="2023-11-03",
        report_date="2023-09-30",
        primary_document_path="10k_primary.txt",
        primary_storage_path=p,
    )


def _sample_form4_filing(tmp_path: Path) -> FilingAggregate:
    xml_content = "<ownershipDocument><issuer><issuerCik>0000320193</issuerCik></issuer></ownershipDocument>"
    p = tmp_path / "form4.xml"
    p.write_text(xml_content, encoding="utf-8")
    acc = AccessionNumber.from_any("0000320193-23-000107")
    cik = Cik.from_raw(320193)
    return FilingAggregate(
        accession=acc,
        primary_cik=cik,
        ciks=(cik,),
        form="4",
        filing_date="2023-11-04",
        primary_document_path="form4.xml",
        primary_storage_path=p,
    )


def test_form4_dormant_and_bypassed(tmp_path: Path) -> None:
    """Ensure non-covered Form 4 returns empty sequences with zero extraction overhead."""
    f4 = _sample_form4_filing(tmp_path)
    client = Edgar()

    sec_seq = client.sections(f4)
    assert len(sec_seq.sections) == 0
    assert sec_seq.family == "4"

    notes_seq = client.notes(f4)
    assert len(notes_seq.notes) == 0

    assert client.toc(f4) is None

    t_sec = build_sections_table([f4])
    assert isinstance(t_sec, pa.Table)
    assert t_sec.num_rows == 0

    t_notes = build_notes_table([f4])
    assert isinstance(t_notes, pa.Table)
    assert t_notes.num_rows == 0


def test_10k_sections_and_notes_detection(tmp_path: Path) -> None:
    """Ensure covered 10-K extracts sections, notes, and lineage metadata."""
    f10k = _sample_10k_filing(tmp_path)
    client = Edgar()

    sec_seq = client.sections(f10k)
    assert len(sec_seq.sections) > 0
    assert sec_seq.payload_sha256 is not None
    assert sec_seq.renderer_version is not None

    notes_seq = client.notes(f10k)
    assert len(notes_seq.notes) == 2
    assert notes_seq.notes[0].note_number == 1
    assert notes_seq.notes[1].note_number == 2
    assert notes_seq.payload_sha256 is not None

    item_1 = client.section(f10k, "1")
    assert item_1 is not None
    assert "The business overview." in item_1


def test_streaming_record_batches_from_iterator(tmp_path: Path) -> None:
    """Ensure builders consume iterators in a single pass without large list materialization."""
    f10k = _sample_10k_filing(tmp_path)
    f4 = _sample_form4_filing(tmp_path)

    gen = (f for f in [f10k, f4])
    cat_t = build_catalog_table(gen)
    assert cat_t.num_rows == 2

    gen_sec = (f for f in [f10k, f4])
    sec_t = build_sections_table(gen_sec)
    assert sec_t.num_rows > 0

    gen_notes = (f for f in [f10k, f4])
    notes_t = build_notes_table(gen_notes)
    assert notes_t.num_rows == 2


def test_filings_result_relational_sql(tmp_path: Path) -> None:
    """Ensure FilingsResult exposes lazy Arrow tables and DuckDB SQL registration."""
    f10k = _sample_10k_filing(tmp_path)
    res = FilingsResult(
        run_id="test-run",
        plan_id="test-plan",
        target_parquet_glob="*.parquet",
        run_state_sqlite_path=tmp_path / "run.sqlite",
        artifacts_root=tmp_path,
        items=(f10k,),
    )

    sec_tbl = res.sections
    assert isinstance(sec_tbl, pa.Table)
    assert sec_tbl.num_rows > 0

    notes_tbl = res.notes
    assert isinstance(notes_tbl, pa.Table)
    assert notes_tbl.num_rows == 2

    sec_df = res.sections_df()
    assert len(sec_df) == sec_tbl.num_rows

    notes_df = res.notes_df()
    assert len(notes_df) == 2

    sql_res = res.sql(
        "SELECT item_identifier, heading FROM sections WHERE item_identifier = 'ITEM 1A'"
    ).fetchall()
    assert len(sql_res) == 1
    assert sql_res[0][0] == "ITEM 1A"

    notes_sql = res.sql(
        "SELECT note_number, note_label FROM notes ORDER BY note_number"
    ).fetchall()
    assert len(notes_sql) == 2
    assert notes_sql[0][0] == 1
