"""Unit tests for the document snapshot assembly query."""

from __future__ import annotations

from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from edgar_sec.domain.document.models import FilingOccurrence
from edgar_sec.domain.identity import AccessionNumber, Cik
from edgar_sec.infra.storage.duckdb import connect, copy_query_to_parquet
from edgar_sec.pipelines.document_storage.checkpoint import (
    DOCUMENT_SNAPSHOT_SCHEMA,
    write_chunk_snapshot,
)
from edgar_sec.pipelines.document_storage.queries import chunk_assembly_query


def _write_chunk(path: Path, start: int, count: int) -> Path:
    occurrences: list[FilingOccurrence] = []
    blobs: dict[str, bytes] = {}
    texts: dict[str, str] = {}
    for index in range(count):
        doc_index = start + index
        occurrence = FilingOccurrence(
            occurrence_id=f"occ_{doc_index}",
            source_cik=Cik.from_raw(f"1000{doc_index}"),
            accession=AccessionNumber(f"000032019{doc_index:01d}-23-000100"),
            document_path="form10k.htm",
            form="10-K",
            filing_date="2023-10-01",
            report_date="2023-09-30",
            doc_id=f"blob_{doc_index}_sha256",
        )
        occurrences.append(occurrence)
        blobs[occurrence.doc_id] = f"<html>{doc_index}</html>".encode()
        texts[occurrence.occurrence_id] = f"Normalized doc {doc_index}"
    write_chunk_snapshot(
        output_path=path,
        occurrences=occurrences,
        raw_blobs=blobs,
        normalized_texts=texts,
    )
    return path


def test_assembly_concatenates_chunks_and_preserves_the_published_sort(
    tmp_path: Path,
) -> None:
    """The sort order is an artifact contract: a snapshot is read back by
    streaming it, so the row order is part of what the snapshot means."""
    chunks_dir = tmp_path / "chunks"
    chunks_dir.mkdir()
    chunk_paths = [
        _write_chunk(chunks_dir / "chunk_0000.parquet", start, 3) for start in (0, 3)
    ]

    artifact = tmp_path / "document_snapshot.parquet"
    with connect() as con:
        total = copy_query_to_parquet(
            con, chunk_assembly_query([str(p) for p in chunk_paths]), artifact
        )

    assert total == 6
    table = pq.read_table(artifact)
    assert table.num_rows == 6
    assert table.schema == DOCUMENT_SNAPSHOT_SCHEMA
    assert table.column("source_cik").to_pylist() == sorted(
        table.column("source_cik").to_pylist()
    )


def test_assembly_escapes_a_chunk_path_containing_a_quote(tmp_path: Path) -> None:
    """A chunk directory is chosen by the caller, so a quoted path is legal input.

    The assembly statement used to interpolate paths without escaping, so a
    quote in the path produced malformed SQL rather than a snapshot.
    """
    quoted_dir = tmp_path / "worker's chunks"
    quoted_dir.mkdir()
    chunk = _write_chunk(quoted_dir / "chunk_0000.parquet", start=0, count=2)

    query = chunk_assembly_query([str(chunk)])
    assert f"{chunk}".replace("'", "''") in query
    assert f"read_parquet('{chunk}')" not in query

    artifact = tmp_path / "out.parquet"
    with connect() as con:
        total = copy_query_to_parquet(con, query, artifact)

    assert total == 2
    assert pq.read_table(artifact).schema == DOCUMENT_SNAPSHOT_SCHEMA


def test_assembly_refuses_an_empty_chunk_list() -> None:
    import pytest

    with pytest.raises(ValueError, match="at least one chunk checkpoint"):
        chunk_assembly_query([])


def test_assembly_output_matches_the_chunk_schema(tmp_path: Path) -> None:
    """The assembled file keeps the chunk schema exactly, so a reader needs no
    knowledge of which stage produced it."""
    chunk = _write_chunk(tmp_path / "chunk_0000.parquet", start=0, count=1)
    artifact = tmp_path / "out.parquet"
    with connect() as con:
        copy_query_to_parquet(con, chunk_assembly_query([str(chunk)]), artifact)

    assert pq.read_schema(artifact) == pa.schema(DOCUMENT_SNAPSHOT_SCHEMA)
