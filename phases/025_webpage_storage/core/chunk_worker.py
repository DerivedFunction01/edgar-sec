"""Acquire one isolated webpage chunk and publish its SQLite records."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from defs.sql import (
    Commit,
    Compare,
    ComparisonOp,
    DoNothing,
    Pragma,
    Select,
    SqlDialect,
    Star,
    Table,
    col,
    insert_values,
    make_sql_executor,
    param,
)

from ..processors import (
    DocumentProcessor,
    NoOpDocumentProcessor,
    execute_processor,
)
from .schemas import (
    ACQUISITION_FAILURES_TABLE,
    COMMITTED_CHUNKS_TABLE,
    DOCUMENT_BLOBS_TABLE,
    FILING_OCCURRENCES_TABLE,
    AcquisitionFailure,
    CommittedChunk,
    DocumentLocator,
    FetchResult,
    FilingOccurrence,
    build_blob,
    create_chunk_schema,
    doc_id,
)


@runtime_checkable
class ArchiveFetcher(Protocol):
    """Protocol for fetching raw document payloads given a DocumentLocator."""

    def fetch(self, locator: DocumentLocator) -> FetchResult: ...


@dataclass(frozen=True, slots=True)
class ChunkFailure:
    locator: DocumentLocator
    status: str
    error: str | None = None


@dataclass(frozen=True, slots=True)
class ChunkResult:
    chunk_id: str
    worker_id: str
    path: Path
    locator_count: int
    fetched_count: int
    occurrence_count: int
    blob_count: int
    failures: tuple[ChunkFailure, ...] = ()
    audit: CommittedChunk | None = None

    @property
    def succeeded(self) -> bool:
        return not self.failures


def _occurrence(raw: FilingOccurrence | Mapping[str, object]) -> FilingOccurrence:
    if isinstance(raw, FilingOccurrence):
        return raw
    return FilingOccurrence.from_row(dict(raw))


def _fetch(fetcher: ArchiveFetcher, locator: DocumentLocator) -> FetchResult:
    result = fetcher.fetch(locator)
    if isinstance(result, FetchResult):
        return result
    if isinstance(result, bytes):
        return FetchResult(locator=locator, payload=result, status="ok")
    if result is None:
        return FetchResult(locator=locator, payload=None, status="missing")
    raise TypeError("ArchiveFetcher.fetch must return FetchResult, bytes, or None")


def _get_metrics(fetcher: object) -> dict[str, Any] | None:
    metrics = getattr(fetcher, "metrics", None)
    if metrics is None:
        metrics = getattr(getattr(fetcher, "_http_client", None), "metrics", None)
    if metrics is not None and hasattr(metrics, "snapshot"):
        return metrics.snapshot()
    return None


def process_chunk(
    chunk_id: str,
    worker_id: str,
    locators: Sequence[DocumentLocator],
    occurrences: Sequence[FilingOccurrence | Mapping[str, object]],
    fetcher: ArchiveFetcher,
    output_path: str | Path,
    progress: Callable[[dict], None] | None = None,
    processor: DocumentProcessor | None = None,
) -> ChunkResult:
    """Fetch locators and stream records directly into a self-contained SQLite chunk database.

    Streaming writes guarantee O(1) RAM usage per worker regardless of chunk size or document
    file sizes. Sub-chunk resumption checks already persisted document_blobs and acquisition_failures
    records so interrupted runs never re-fetch already stored documents.
    The _committed_chunks table is written only after 100% of chunk locators have been processed.
    """
    if not chunk_id or not worker_id:
        raise ValueError("chunk_id and worker_id are required")

    effective_processor = processor or NoOpDocumentProcessor()
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(exist_ok=True)

    normalized_occurrences = tuple(_occurrence(row) for row in occurrences)
    occurrences_by_doc_id: dict[str, list[FilingOccurrence]] = defaultdict(list)
    for occ in normalized_occurrences:
        occurrences_by_doc_id[occ.doc_id].append(occ)

    unique_documents: list[DocumentLocator] = []
    seen_docs: set[tuple[str, str]] = set()
    locators_by_doc_id: dict[str, DocumentLocator] = {}
    for locator in locators:
        doc_key = (locator.accession, locator.document_path)
        locator_doc_id = doc_id(locator.accession, locator.document_path)
        locators_by_doc_id[locator_doc_id] = locator
        if doc_key not in seen_docs:
            seen_docs.add(doc_key)
            unique_documents.append(locator)

    executor = make_sql_executor(path, dialect=SqlDialect.SQLITE)
    try:
        # Fast write PRAGMAs for isolated chunk database
        for pragma_stmt in (
            Pragma("synchronous", "OFF"),
            Pragma("journal_mode", "WAL"),
            Pragma("cache_size", -16000),
        ):
            executor.exec(executor.compiler.compile(pragma_stmt))

        create_chunk_schema(executor)

        # Check if already 100% committed
        committed_rows = executor.query(
            executor.compiler.compile(
                Select(
                    source=Table(COMMITTED_CHUNKS_TABLE),
                    projection=(Star(),),
                    where=Compare(col("chunk_id"), ComparisonOp.EQ, param(chunk_id)),
                )
            )
        )
        if committed_rows:
            committed_audit = CommittedChunk.from_row(committed_rows[0])
            blobs_in_db = executor.query(
                executor.compiler.compile(
                    Select(
                        source=Table(DOCUMENT_BLOBS_TABLE),
                        projection=(col("doc_id"),),
                    )
                )
            )
            failures_in_db = executor.query(
                executor.compiler.compile(
                    Select(
                        source=Table(ACQUISITION_FAILURES_TABLE),
                        projection=(
                            col("doc_id"),
                            col("status"),
                            col("error_message"),
                        ),
                    )
                )
            )
            reconstructed_failures = tuple(
                ChunkFailure(
                    locator=locators_by_doc_id.get(
                        str(row["doc_id"]),
                        DocumentLocator(
                            locator_key="",
                            accession="",
                            document_path="",
                            archive_url="",
                            form="",
                        ),
                    ),
                    status=str(row["status"]),
                    error=str(row.get("error_message") or ""),
                )
                for row in failures_in_db
            )
            return ChunkResult(
                chunk_id=chunk_id,
                worker_id=committed_audit.worker_id,
                path=path,
                locator_count=len(unique_documents),
                fetched_count=len(blobs_in_db),
                occurrence_count=committed_audit.record_count,
                blob_count=len(blobs_in_db),
                failures=reconstructed_failures,
                audit=committed_audit,
            )

        # Sub-chunk resumption: query already persisted items in this chunk DB
        existing_blob_rows = executor.query(
            executor.compiler.compile(
                Select(
                    source=Table(DOCUMENT_BLOBS_TABLE),
                    projection=(col("doc_id"),),
                )
            )
        )
        existing_blobs = {str(row["doc_id"]) for row in existing_blob_rows}

        existing_failure_rows = executor.query(
            executor.compiler.compile(
                Select(
                    source=Table(ACQUISITION_FAILURES_TABLE),
                    projection=(
                        col("doc_id"),
                        col("status"),
                        col("error_message"),
                    ),
                )
            )
        )
        existing_failures = {
            str(row["doc_id"]): (
                str(row["status"]),
                str(row.get("error_message") or ""),
            )
            for row in existing_failure_rows
        }

        chunk_failures: list[ChunkFailure] = [
            ChunkFailure(
                locator=locators_by_doc_id[did],
                status=st_err[0],
                error=st_err[1],
            )
            for did, st_err in existing_failures.items()
            if did in locators_by_doc_id
        ]

        def emit(event: dict) -> None:
            if progress is not None:
                with suppress(Exception):
                    progress(event)

        # Stream acquisitions directly into SQLite
        for locator in unique_documents:
            target_doc_id = doc_id(locator.accession, locator.document_path)
            if target_doc_id in existing_blobs:
                emit(
                    {
                        "type": "document_done",
                        "status": "cached",
                        "doc_id": target_doc_id,
                        "metrics": _get_metrics(fetcher),
                    }
                )
                continue
            if target_doc_id in existing_failures:
                emit(
                    {
                        "type": "document_done",
                        "status": existing_failures[target_doc_id][0],
                        "doc_id": target_doc_id,
                        "metrics": _get_metrics(fetcher),
                    }
                )
                continue

            try:
                fetched = _fetch(fetcher, locator)
            except (OSError, RuntimeError, TypeError, ValueError) as exc:
                err_msg = str(exc) or type(exc).__name__
                chunk_failures.append(ChunkFailure(locator, "failed", err_msg))
                failure_record = AcquisitionFailure(
                    doc_id=target_doc_id,
                    accession=locator.accession,
                    document_path=locator.document_path,
                    status="failed",
                    error_message=err_msg,
                    attempted_at=datetime.now(UTC).isoformat(),
                )
                executor.exec(
                    executor.compiler.compile(
                        insert_values(
                            ACQUISITION_FAILURES_TABLE,
                            failure_record.to_row(),
                            on_conflict=DoNothing(),
                        )
                    )
                )
                executor.exec(executor.compiler.compile(Commit()))
                emit(
                    {
                        "type": "document_done",
                        "status": "failed",
                        "doc_id": target_doc_id,
                        "error": err_msg,
                        "metrics": _get_metrics(fetcher),
                    }
                )
                continue

            if fetched.status != "ok" or fetched.payload is None:
                status = fetched.status
                err_msg = fetched.error or fetched.status
                chunk_failures.append(ChunkFailure(locator, status, err_msg))
                failure_record = AcquisitionFailure(
                    doc_id=target_doc_id,
                    accession=locator.accession,
                    document_path=locator.document_path,
                    status=status,
                    error_message=err_msg,
                    attempted_at=datetime.now(UTC).isoformat(),
                )
                executor.exec(
                    executor.compiler.compile(
                        insert_values(
                            ACQUISITION_FAILURES_TABLE,
                            failure_record.to_row(),
                            on_conflict=DoNothing(),
                        )
                    )
                )
                executor.exec(executor.compiler.compile(Commit()))
                emit(
                    {
                        "type": "document_done",
                        "status": status,
                        "doc_id": target_doc_id,
                        "error": err_msg,
                        "metrics": _get_metrics(fetcher),
                    }
                )
                continue

            # Process document (cleaning, normalization, or pass-through, sync or async)
            processed = execute_processor(effective_processor, fetched.payload, locator)

            # Succeeded: compress and stream directly to SQLite
            blob = build_blob(
                locator.accession, locator.document_path, processed.payload
            )
            blob_stmt = insert_values(
                DOCUMENT_BLOBS_TABLE,
                blob.to_row(),
                on_conflict=DoNothing(),
            )
            executor.exec(executor.compiler.compile(blob_stmt))

            # Store associated occurrences
            matching_occs = occurrences_by_doc_id.get(target_doc_id, [])
            if matching_occs:
                occ_stmt = insert_values(
                    FILING_OCCURRENCES_TABLE,
                    [occ.to_row() for occ in matching_occs],
                    on_conflict=DoNothing(),
                )
                executor.exec(executor.compiler.compile(occ_stmt))

            executor.exec(executor.compiler.compile(Commit()))
            existing_blobs.add(target_doc_id)
            emit(
                {
                    "type": "document_done",
                    "status": "ok",
                    "doc_id": target_doc_id,
                    "byte_size": blob.byte_size,
                    "metrics": _get_metrics(fetcher),
                }
            )

        # Count total stored occurrences and blobs
        final_occurrences = executor.query(
            executor.compiler.compile(
                Select(
                    source=Table(FILING_OCCURRENCES_TABLE),
                    projection=(col("occurrence_id"),),
                )
            )
        )
        final_blobs = executor.query(
            executor.compiler.compile(
                Select(
                    source=Table(DOCUMENT_BLOBS_TABLE),
                    projection=(col("doc_id"),),
                )
            )
        )

        audit = CommittedChunk(
            chunk_id=chunk_id,
            record_count=len(final_occurrences),
            worker_id=worker_id,
            committed_at=datetime.now(UTC).isoformat(),
        )
        executor.exec(
            executor.compiler.compile(
                insert_values(
                    COMMITTED_CHUNKS_TABLE,
                    audit.to_row(),
                    on_conflict=DoNothing(),
                )
            )
        )
        executor.exec(executor.compiler.compile(Commit()))

        return ChunkResult(
            chunk_id=chunk_id,
            worker_id=worker_id,
            path=path,
            locator_count=len(unique_documents),
            fetched_count=len(final_blobs),
            occurrence_count=len(final_occurrences),
            blob_count=len(final_blobs),
            failures=tuple(chunk_failures),
            audit=audit,
        )
    finally:
        executor.close()


def worker(*args, **kwargs) -> ChunkResult:
    """Compatibility entry point for callers naming the operation ``worker``."""
    return process_chunk(*args, **kwargs)


__all__ = ["ArchiveFetcher", "ChunkFailure", "ChunkResult", "process_chunk", "worker"]
