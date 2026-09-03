"""Preflight lookup and validation of completed chunk databases."""

from __future__ import annotations

from pathlib import Path

from defs.sql import (
    Compare,
    ComparisonOp,
    Select,
    SqlDialect,
    Table,
    col,
    make_sql_executor,
    param,
)

from .chunk_persistence import ChunkFailure, ChunkResult
from .schemas import (
    ACQUISITION_FAILURE_COLUMNS,
    ACQUISITION_FAILURES_TABLE,
    COMMITTED_CHUNK_COLUMNS,
    COMMITTED_CHUNKS_TABLE,
    DOCUMENT_BLOBS_TABLE,
    FILING_OCCURRENCES_TABLE,
    NORMALIZED_SCHEMA_VERSION,
    CommittedChunk,
    DocumentLocator,
)


def find_completed_chunk_db(run_paths, attempt_id: str, chunk_id: str) -> Path | None:
    matches = sorted(run_paths.workers_root.glob(f"*/{attempt_id}/{chunk_id}.db"))
    for path in matches:
        if path.is_file():
            return path
    return None


def try_load_completed_chunk(
    chunk_id: str, chunk_path: Path, processor=None
) -> ChunkResult | None:
    if not chunk_path.is_file():
        return None
    try:
        executor = make_sql_executor(chunk_path, dialect=SqlDialect.SQLITE)
        try:
            audit_row = executor.query_one(
                executor.compiler.compile(
                    Select(
                        source=Table(COMMITTED_CHUNKS_TABLE),
                        projection=tuple(col(c) for c in COMMITTED_CHUNK_COLUMNS),
                        where=Compare(
                            col("chunk_id"), ComparisonOp.EQ, param(chunk_id)
                        ),
                    )
                )
            )
            if audit_row is None:
                return None
            audit = CommittedChunk.from_row(audit_row)
            expected_fingerprint = (
                getattr(processor, "processor_fingerprint", "custom:unspecified")
                if processor is not None
                else "raw-only"
            )
            if processor is None:
                pass
            elif (
                audit.processor_fingerprint != expected_fingerprint
                or audit.normalized_schema_version != NORMALIZED_SCHEMA_VERSION
            ):
                return None
            blobs = executor.query(
                executor.compiler.compile(
                    Select(
                        source=Table(DOCUMENT_BLOBS_TABLE),
                        projection=(col("doc_id"),),
                    )
                )
            )
            occurrences = executor.query(
                executor.compiler.compile(
                    Select(
                        source=Table(FILING_OCCURRENCES_TABLE),
                        projection=(col("occurrence_id"),),
                    )
                )
            )
            failure_rows = executor.query(
                executor.compiler.compile(
                    Select(
                        source=Table(ACQUISITION_FAILURES_TABLE),
                        projection=tuple(col(c) for c in ACQUISITION_FAILURE_COLUMNS),
                    )
                )
            )
            failures = tuple(
                ChunkFailure(
                    locator=DocumentLocator(
                        locator_key=str(row["doc_id"]),
                        accession=str(row["accession"]),
                        document_path=str(row["document_path"]),
                        archive_url="",
                    ),
                    status=str(row["status"]),
                    error=str(row["error_message"] or row["status"]),
                )
                for row in failure_rows
            )
            return ChunkResult(
                chunk_id=chunk_id,
                worker_id=audit.worker_id,
                path=chunk_path,
                locator_count=len(blobs) + len(failure_rows),
                fetched_count=len(blobs),
                occurrence_count=len(occurrences),
                blob_count=len(blobs),
                failures=failures,
                audit=audit,
            )
        finally:
            executor.close()
    except Exception:  # noqa: BLE001 - corrupted or incomplete chunk dbs are reprocessed
        return None


__all__ = ["find_completed_chunk_db", "try_load_completed_chunk"]
