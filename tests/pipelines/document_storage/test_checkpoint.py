"""Unit tests for document_storage.checkpoint."""

from __future__ import annotations

from pathlib import Path

import pyarrow.parquet as pq

from edgar_sec.domain.document.models import (
    FilingOccurrence,
)
from edgar_sec.domain.identity import AccessionNumber, Cik
from edgar_sec.pipelines.document_storage.checkpoint import (
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
    meta = pq.read_metadata(chunk_file)
    assert meta.row_group(0).column(0).compression == "ZSTD"
