"""Unit tests for document_parquet chunk snapshots and DuckDB assembly."""

from __future__ import annotations

from pathlib import Path

import pyarrow.parquet as pq

from edgar_sec.domain.document.models import (
    FilingOccurrence,
)
from edgar_sec.domain.identity import AccessionNumber, Cik
from edgar_sec.infra.storage.document_parquet import (
    DOCUMENT_SNAPSHOT_SCHEMA,
    assemble_document_snapshots,
    validate_chunk_snapshot,
    write_chunk_snapshot,
)


def _make_sample_occurrence(idx: int) -> tuple[FilingOccurrence, bytes]:
    acc_str = f"000032019{idx:01d}-23-000100"
    acc = AccessionNumber(acc_str)
    cik = Cik.from_raw(f"1000{idx}")
    path = "form10k.htm"
    blob_hash = f"blob_{idx}_sha256"
    raw_payload = f"<html>Content {idx}</html>".encode()

    occ = FilingOccurrence(
        occurrence_id=f"occ_{idx}",
        source_cik=cik,
        accession=acc,
        document_path=path,
        form="10-K",
        filing_date="2023-10-01",
        report_date="2023-09-30",
        doc_id=blob_hash,
    )
    return occ, raw_payload


def test_write_and_validate_chunk_snapshot(tmp_path: Path) -> None:
    chunk_file = tmp_path / "chunk_00000.parquet"
    occs = []
    blobs = {}
    texts = {}

    for i in range(5):
        occ, blob = _make_sample_occurrence(i)
        occs.append(occ)
        blobs[occ.doc_id] = blob
        texts[occ.occurrence_id] = f"Normalized text {i}"

    written_path = write_chunk_snapshot(
        output_path=chunk_file,
        occurrences=occs,
        raw_blobs=blobs,
        normalized_texts=texts,
    )
    assert written_path.is_file()

    stats = validate_chunk_snapshot(written_path)
    assert stats["num_rows"] == 5

    # Check compression
    meta = pq.read_metadata(written_path)
    assert meta.row_group(0).column(0).compression == "ZSTD"


def test_assemble_document_snapshots(tmp_path: Path) -> None:
    chunks_dir = tmp_path / "chunks"
    chunks_dir.mkdir()

    chunk_paths = []
    # Create two chunk files
    for c in range(2):
        chunk_file = chunks_dir / f"chunk_{c:04d}.parquet"
        occs = []
        blobs = {}
        texts = {}
        for i in range(3):
            doc_idx = c * 3 + i
            occ, blob = _make_sample_occurrence(doc_idx)
            occs.append(occ)
            blobs[occ.doc_id] = blob
            texts[occ.occurrence_id] = f"Normalized doc {doc_idx}"

        write_chunk_snapshot(
            output_path=chunk_file,
            occurrences=occs,
            raw_blobs=blobs,
            normalized_texts=texts,
        )
        chunk_paths.append(chunk_file)

    final_snapshot = tmp_path / "document_snapshot.parquet"
    total_rows = assemble_document_snapshots(chunk_paths, final_snapshot)

    assert total_rows == 6
    assert final_snapshot.is_file()

    table = pq.read_table(final_snapshot)
    assert table.num_rows == 6
    assert table.schema == DOCUMENT_SNAPSHOT_SCHEMA
