"""Fetch-result persistence and concurrent acquisition for isolated chunks."""

from __future__ import annotations

import hashlib
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
    Select,
    Table,
    col,
    insert_values,
    param,
)

from ..processors import DocumentProcessor, execute_processor
from .schemas import (
    ACQUISITION_FAILURES_TABLE,
    DOCUMENT_BLOBS_TABLE,
    FILING_OCCURRENCES_TABLE,
    NORMALIZATION_FAILURES_TABLE,
    NORMALIZED_DOCUMENTS_TABLE,
    NORMALIZED_SCHEMA_VERSION,
    AcquisitionFailure,
    CommittedChunk,
    DocumentLocator,
    FetchResult,
    FilingOccurrence,
    NormalizationFailure,
    NormalizedDocument,
    build_blob,
    decompress_payload,
    deterministic_metadata,
    doc_id,
    normalized_artifact_id,
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


def _load_raw_payload(executor, target_doc_id: str) -> bytes | None:
    rows = executor.query(
        executor.compiler.compile(
            Select(
                source=Table(DOCUMENT_BLOBS_TABLE),
                projection=(col("raw_payload"),),
                where=Compare(col("doc_id"), ComparisonOp.EQ, param(target_doc_id)),
                limit=1,
            )
        )
    )
    if not rows:
        return None
    return decompress_payload(rows[0]["raw_payload"])


def _persist_fetch_result(
    locator: DocumentLocator,
    fetched: FetchResult | None,
    *,
    fetcher: ArchiveFetcher,
    processor: DocumentProcessor | None,
    executor,
    occurrences_by_doc_id: Mapping[str, Sequence[FilingOccurrence]],
    existing_blobs: set[str],
    existing_failures: Mapping[str, tuple[str, str]],
    chunk_failures: list[ChunkFailure],
    progress: Callable[[dict], None] | None,
    error: str | None = None,
) -> str:
    """Persist one fetch result into the chunk database and emit a progress event.

    The coordinator owns the SQLite connection and progress callbacks; worker
    threads only supply the completed ``FetchResult``. Returns the terminal
    status for this document.
    """
    target_doc_id = doc_id(locator.accession, locator.document_path)

    def emit(event: dict) -> None:
        if progress is not None:
            with suppress(Exception):
                progress(event)

    if error is not None:
        err_msg = error
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
        return "failed"

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
        return status

    # The blob is always the exact fetched source; normalization is separate.
    raw_payload = fetched.payload
    blob = build_blob(locator.accession, locator.document_path, raw_payload)
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

    if processor is not None:
        try:
            processed = execute_processor(processor, raw_payload, locator)
            normalized = NormalizedDocument(
                normalized_artifact_id=normalized_artifact_id(
                    blob.raw_payload_sha256, processed.processor_fingerprint
                ),
                source_doc_id=target_doc_id,
                byte_size=processed.byte_size,
                normalized_payload=processed.payload,
                payload_sha256=hashlib.sha256(processed.payload).hexdigest(),
                mime_type=processed.mime_type,
                representation=processed.representation,
                processor_fingerprint=processed.processor_fingerprint,
                schema_version=NORMALIZED_SCHEMA_VERSION,
                processor_metadata=deterministic_metadata(processed.metadata),
            )
            executor.exec(
                executor.compiler.compile(
                    insert_values(
                        NORMALIZED_DOCUMENTS_TABLE,
                        normalized.to_row(),
                        on_conflict=DoNothing(),
                    )
                )
            )
        except Exception as exc:  # noqa: BLE001 - failures are durable records
            failure = NormalizationFailure(
                source_doc_id=target_doc_id,
                processor_fingerprint=getattr(
                    processor, "processor_fingerprint", "custom:unspecified"
                ),
                schema_version=NORMALIZED_SCHEMA_VERSION,
                error_message=str(exc) or type(exc).__name__,
                attempted_at=datetime.now(UTC).isoformat(),
            )
            executor.exec(
                executor.compiler.compile(
                    insert_values(
                        NORMALIZATION_FAILURES_TABLE,
                        failure.to_row(),
                        on_conflict=DoNothing(),
                    )
                )
            )

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
    return "ok"


def _run_concurrent_acquisitions(
    locators: Sequence[DocumentLocator],
    *,
    fetcher: ArchiveFetcher,
    processor: DocumentProcessor,
    executor,
    occurrences_by_doc_id: Mapping[str, Sequence[FilingOccurrence]],
    existing_blobs: set[str],
    existing_failures: Mapping[str, tuple[str, str]],
    chunk_failures: list[ChunkFailure],
    progress: Callable[[dict], None] | None,
    fetch_workers: int,
) -> None:
    """Fetch uncached locators across a bounded thread pool; the coordinator
    owns the SQLite connection and progress callbacks, so worker threads only
    call ``fetcher.fetch`` and return the completed ``FetchResult``."""
    from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

    pending: list[DocumentLocator] = [
        locator
        for locator in locators
        if doc_id(locator.accession, locator.document_path) not in existing_blobs
        and doc_id(locator.accession, locator.document_path) not in existing_failures
    ]
    if not pending:
        return

    with ThreadPoolExecutor(max_workers=max(1, fetch_workers)) as pool:
        locator_iter = iter(pending)
        future_to_locator: dict = {
            pool.submit(_fetch, fetcher, locator): locator
            for locator in (next(locator_iter, None) for _ in range(fetch_workers))
            if locator is not None
        }
        while future_to_locator:
            completed, _ = wait(future_to_locator, return_when=FIRST_COMPLETED)
            for future in completed:
                locator = future_to_locator.pop(future)
                try:
                    fetched = future.result()
                except (OSError, RuntimeError, TypeError, ValueError) as exc:
                    _persist_fetch_result(
                        locator,
                        None,
                        fetcher=fetcher,
                        processor=processor,
                        executor=executor,
                        occurrences_by_doc_id=occurrences_by_doc_id,
                        existing_blobs=existing_blobs,
                        existing_failures=existing_failures,
                        chunk_failures=chunk_failures,
                        progress=progress,
                        error=str(exc) or type(exc).__name__,
                    )
                else:
                    _persist_fetch_result(
                        locator,
                        fetched,
                        fetcher=fetcher,
                        processor=processor,
                        executor=executor,
                        occurrences_by_doc_id=occurrences_by_doc_id,
                        existing_blobs=existing_blobs,
                        existing_failures=existing_failures,
                        chunk_failures=chunk_failures,
                        progress=progress,
                    )
                replacement = next(locator_iter, None)
                if replacement is not None:
                    future_to_locator[pool.submit(_fetch, fetcher, replacement)] = (
                        replacement
                    )


__all__ = ["ArchiveFetcher", "ChunkFailure", "ChunkResult"]
