"""Acquire one isolated webpage chunk and publish its SQLite records."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path

from defs.sql import (
    Commit,
    Compare,
    ComparisonOp,
    Delete,
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

from ..processors import DocumentProcessor
from .chunk_persistence import (
    ArchiveFetcher,
    ChunkFailure,
    ChunkResult,
    _fetch,
    _get_metrics,
    _load_raw_payload,
    _persist_fetch_result,
    _run_concurrent_acquisitions,
)
from .schemas import (
    ACQUISITION_FAILURES_TABLE,
    COMMITTED_CHUNKS_TABLE,
    DOCUMENT_BLOBS_TABLE,
    FILING_OCCURRENCES_TABLE,
    NORMALIZATION_FAILURES_TABLE,
    NORMALIZED_DOCUMENTS_TABLE,
    NORMALIZED_SCHEMA_VERSION,
    CommittedChunk,
    DocumentLocator,
    FetchResult,
    FilingOccurrence,
    create_chunk_schema,
    doc_id,
)


def _occurrence(raw: FilingOccurrence | Mapping[str, object]) -> FilingOccurrence:
    if isinstance(raw, FilingOccurrence):
        return raw
    return FilingOccurrence.from_row(dict(raw))


def process_chunk(
    chunk_id: str,
    worker_id: str,
    locators: Sequence[DocumentLocator],
    occurrences: Sequence[FilingOccurrence | Mapping[str, object]],
    fetcher: ArchiveFetcher,
    output_path: str | Path,
    progress: Callable[[dict], None] | None = None,
    processor: DocumentProcessor | None = None,
    fetch_workers: int = 1,
    allow_append: bool = False,
    retry_failures: bool = False,
) -> ChunkResult:
    """Fetch locators and stream records directly into a self-contained SQLite chunk database.

    Streaming writes guarantee O(1) RAM usage per worker regardless of chunk size or document
    file sizes. Sub-chunk resumption checks already persisted document_blobs and acquisition_failures
    records so interrupted runs never re-fetch already stored documents.
    The _committed_chunks table is written only after 100% of chunk locators have been processed.
    ``allow_append`` is reserved for mutable fixture caches: it reopens a
    completed audit row, skips existing blobs, and refreshes the audit after
    processing any new locators. Normal production chunks remain terminal.
    """
    if not chunk_id or not worker_id:
        raise ValueError("chunk_id and worker_id are required")

    effective_processor = processor
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
        committed_audit_row: dict | None = None
        if committed_rows:
            candidate_audit = CommittedChunk.from_row(committed_rows[0])
            if processor is None:
                committed_audit_row = committed_rows[0]
            else:
                expected_fingerprint = getattr(
                    processor, "processor_fingerprint", "custom:unspecified"
                )
                if (
                    candidate_audit.processor_fingerprint == expected_fingerprint
                    and candidate_audit.normalized_schema_version
                    == NORMALIZED_SCHEMA_VERSION
                ):
                    committed_audit_row = committed_rows[0]
                else:
                    # Stale processing contract: a committed chunk may never
                    # satisfy a run with a different processor fingerprint. Drop
                    # the audit row so the chunk is reprocessed; raw blobs and
                    # occurrences are reused through sub-chunk resumption.
                    executor.exec(
                        executor.compiler.compile(Delete(table=COMMITTED_CHUNKS_TABLE))
                    )
                    executor.exec(executor.compiler.compile(Commit()))

        if committed_audit_row is not None and not allow_append:
            committed_audit = CommittedChunk.from_row(committed_audit_row)
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
        existing_normalized = {
            str(row["source_doc_id"]): str(row["processor_fingerprint"])
            for row in executor.query(
                executor.compiler.compile(
                    Select(
                        source=Table(NORMALIZED_DOCUMENTS_TABLE),
                        projection=(
                            col("source_doc_id"),
                            col("processor_fingerprint"),
                        ),
                    )
                )
            )
        }
        existing_normalization_failures = {
            str(row["source_doc_id"]): str(row["processor_fingerprint"])
            for row in executor.query(
                executor.compiler.compile(
                    Select(
                        source=Table(NORMALIZATION_FAILURES_TABLE),
                        projection=(
                            col("source_doc_id"),
                            col("processor_fingerprint"),
                        ),
                    )
                )
            )
        }

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
        if retry_failures:
            current_doc_ids = {
                doc_id(locator.accession, locator.document_path)
                for locator in unique_documents
            }
            for row in existing_failure_rows:
                if str(row["doc_id"]) in current_doc_ids:
                    executor.exec(
                        executor.compiler.compile(
                            Delete(
                                table=ACQUISITION_FAILURES_TABLE,
                                where=Compare(
                                    col("doc_id"),
                                    ComparisonOp.EQ,
                                    param(str(row["doc_id"])),
                                ),
                            )
                        )
                    )
            executor.exec(executor.compiler.compile(Commit()))
            existing_failure_rows = [
                row
                for row in existing_failure_rows
                if str(row["doc_id"]) not in current_doc_ids
            ]
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

        # A raw-only interrupted run must be normalizable without treating its
        # raw blob as a completed processor result or fetching it again.
        if processor is not None:
            processor_fingerprint = getattr(
                processor, "processor_fingerprint", "custom:unspecified"
            )
            for locator in unique_documents:
                target_doc_id = doc_id(locator.accession, locator.document_path)
                if target_doc_id not in existing_blobs:
                    continue
                if existing_normalized.get(target_doc_id) == processor_fingerprint:
                    continue
                if (
                    existing_normalization_failures.get(target_doc_id)
                    == processor_fingerprint
                ):
                    continue
                raw_payload = _load_raw_payload(executor, target_doc_id)
                if raw_payload is None:
                    continue
                _persist_fetch_result(
                    locator,
                    FetchResult(locator, raw_payload, "ok"),
                    fetcher=fetcher,
                    processor=processor,
                    executor=executor,
                    occurrences_by_doc_id=occurrences_by_doc_id,
                    existing_blobs=existing_blobs,
                    existing_failures=existing_failures,
                    chunk_failures=chunk_failures,
                    progress=progress,
                )

        def emit(event: dict) -> None:
            if progress is not None:
                with suppress(Exception):
                    progress(event)

        if fetch_workers > 1:
            _run_concurrent_acquisitions(
                unique_documents,
                fetcher=fetcher,
                processor=effective_processor,
                executor=executor,
                occurrences_by_doc_id=occurrences_by_doc_id,
                existing_blobs=existing_blobs,
                existing_failures=existing_failures,
                chunk_failures=chunk_failures,
                progress=progress,
                fetch_workers=fetch_workers,
            )
        else:
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
                    _persist_fetch_result(
                        locator,
                        None,
                        fetcher=fetcher,
                        processor=effective_processor,
                        executor=executor,
                        occurrences_by_doc_id=occurrences_by_doc_id,
                        existing_blobs=existing_blobs,
                        existing_failures=existing_failures,
                        chunk_failures=chunk_failures,
                        progress=progress,
                        error=str(exc) or type(exc).__name__,
                    )
                    continue

                _persist_fetch_result(
                    locator,
                    fetched,
                    fetcher=fetcher,
                    processor=effective_processor,
                    executor=executor,
                    occurrences_by_doc_id=occurrences_by_doc_id,
                    existing_blobs=existing_blobs,
                    existing_failures=existing_failures,
                    chunk_failures=chunk_failures,
                    progress=progress,
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
            processor_fingerprint=(
                getattr(processor, "processor_fingerprint", "custom:unspecified")
                if processor is not None
                else "raw-only"
            ),
            normalized_schema_version=NORMALIZED_SCHEMA_VERSION,
        )
        if allow_append and committed_audit_row is not None:
            executor.exec(
                executor.compiler.compile(
                    Delete(
                        table=COMMITTED_CHUNKS_TABLE,
                        where=Compare(
                            col("chunk_id"), ComparisonOp.EQ, param(chunk_id)
                        ),
                    )
                )
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
