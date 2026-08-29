from __future__ import annotations

import importlib
from pathlib import Path

from defs.sql import Commit, insert_values, make_sql_executor

schemas = importlib.import_module("phases.025_webpage_storage.core.schemas")
merger = importlib.import_module("phases.025_webpage_storage.core.partition_merger")


def _chunk(path: Path, chunk_id: str, *, duplicate_doc: bool = False) -> None:
    path.touch()
    executor = make_sql_executor(path, dialect="sqlite")
    schemas.create_chunk_schema(executor)
    blob = {
        "doc_id": "doc-1" if duplicate_doc else f"doc-{chunk_id}",
        "accession": f"acc-{chunk_id}",
        "document_path": "index.html",
        "byte_size": 4,
        "mime_type": schemas.MIME_HTML,
        "raw_payload": b"data",
    }
    occurrence = {
        "occurrence_id": f"occ-{chunk_id}",
        "source_cik": "0000000001",
        "accession": f"acc-{chunk_id}",
        "document_path": "index.html",
        "form": "10-K",
        "filing_date": "2024-01-01",
        "report_date": None,
        "doc_id": blob["doc_id"],
    }
    audit = {
        "chunk_id": chunk_id,
        "record_count": 1,
        "worker_id": "worker-1",
        "committed_at": "2024-01-01 00:00:00",
    }
    for table, row in (
        (schemas.DOCUMENT_BLOBS_TABLE, blob),
        (schemas.FILING_OCCURRENCES_TABLE, occurrence),
        (schemas.COMMITTED_CHUNKS_TABLE, audit),
    ):
        executor.exec(executor.compiler.compile(insert_values(table, row)))
    executor.exec(executor.compiler.compile(Commit()))
    executor.close()


def _rows(path: Path, table: str) -> list[dict]:
    executor = make_sql_executor(path, dialect="sqlite")
    if table == schemas.DOCUMENT_BLOBS_TABLE:
        columns = schemas.BLOB_COLUMNS
    elif table == schemas.FILING_OCCURRENCES_TABLE:
        columns = schemas.OCCURRENCE_COLUMNS
    else:
        columns = schemas.COMMITTED_CHUNK_COLUMNS
    rows = executor.query(
        executor.compiler.compile(merger._select_columns(table, columns))
    )
    executor.close()
    return rows


def test_merge_partition_attaches_and_copies_all_tables(tmp_path: Path) -> None:
    chunk = tmp_path / "chunk-00001.db"
    partition = tmp_path / "partition.db"
    _chunk(chunk, "chunk-00001")

    result = merger.merge_partition(partition, [chunk])

    assert result.committed_chunk_ids == ("chunk-00001",)
    assert result.audit_rows == 1
    assert len(_rows(partition, schemas.DOCUMENT_BLOBS_TABLE)) == 1
    assert len(_rows(partition, schemas.FILING_OCCURRENCES_TABLE)) == 1
    assert (
        _rows(partition, schemas.COMMITTED_CHUNKS_TABLE)[0]["chunk_id"] == "chunk-00001"
    )


def test_merge_partition_deduplicates_blobs_and_is_idempotent(tmp_path: Path) -> None:
    first = tmp_path / "chunk-00001.db"
    second = tmp_path / "chunk-00002.db"
    partition = tmp_path / "partition.db"
    _chunk(first, "chunk-00001", duplicate_doc=True)
    _chunk(second, "chunk-00002", duplicate_doc=True)

    initial = merger.merge_partition(partition, [first, second])
    rerun = merger.merge_partition(partition, [first, second])

    assert initial.audit_rows == 2
    assert rerun.committed_chunk_ids == ()
    assert set(rerun.skipped_chunk_ids) == {"chunk-00001", "chunk-00002"}
    assert len(_rows(partition, schemas.DOCUMENT_BLOBS_TABLE)) == 1
    assert len(_rows(partition, schemas.FILING_OCCURRENCES_TABLE)) == 2
    assert len(_rows(partition, schemas.COMMITTED_CHUNKS_TABLE)) == 2
