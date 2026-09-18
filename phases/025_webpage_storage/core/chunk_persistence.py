"""Fetch-result persistence and concurrent acquisition for isolated chunks."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from defs.runtime.memory import reclaim
from defs.sql import (
    Commit,
    DoNothing,
    insert_values,
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
    compress_payload,
    deterministic_metadata,
    doc_id,
    normalized_artifact_id,
)


@runtime_checkable
class ArchiveFetcher(Protocol):
    """Protocol for fetching raw document payloads given a DocumentLocator."""

    def fetch(self, locator: DocumentLocator) -> FetchResult: ...


# Consumer-side reclaim thresholds: after either bound is reached, the
# coordinator collects cycles and returns free C heap pages (selectolax
# trees, decompressed payloads) to the operating system. This keeps worker
# RSS near the per-document working set instead of the per-chunk high-water
# mark. Machine-derived bounds, never persisted.
_RECLAIM_BYTES_THRESHOLD = 64 * 1024 * 1024
_RECLAIM_DOCS_THRESHOLD = 64
# Bounded FIFO item cap; payload bytes are additionally bounded by
# _PREFETCH_BYTES_BUDGET via the producer-held semaphore.
_PREFETCH_ITEM_CAP = 8
_PREFETCH_BYTES_BUDGET = 96 * 1024 * 1024


class _ByteBudget:
    """Condition-backed byte budget for prefetched raw payloads.

    A semaphore counts items, not bytes.  This budget reserves the actual
    payload size and permits one oversized payload so a document larger than
    the nominal budget cannot deadlock the producer.
    """

    def __init__(self, limit: int) -> None:
        if limit <= 0:
            raise ValueError("byte budget must be positive")
        import threading

        self._limit = limit
        self._used = 0
        self._condition = threading.Condition()

    def acquire(self, size: int) -> None:
        if size <= 0:
            return
        with self._condition:
            while self._used and self._used + size > self._limit:
                self._condition.wait()
            self._used += size

    def release(self, size: int) -> None:
        if size <= 0:
            return
        with self._condition:
            self._used = max(0, self._used - size)
            self._condition.notify_all()

    @property
    def used(self) -> int:
        with self._condition:
            return self._used


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
                normalized_payload=compress_payload(processed.payload),
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


def _run_pipelined_acquisitions(
    locators: Sequence[DocumentLocator],
    *,
    fetcher: ArchiveFetcher,
    processor: DocumentProcessor | None,
    executor,
    occurrences_by_doc_id: Mapping[str, Sequence[FilingOccurrence]],
    existing_blobs: set[str],
    existing_failures: Mapping[str, tuple[str, str]],
    chunk_failures: list[ChunkFailure],
    progress: Callable[[dict], None] | None,
    fetch_workers: int = 1,
) -> None:
    """Acquire and persist uncached locators via a bounded producer-consumer pipeline.

    Lightweight fetch threads pull raw payloads from the fetcher and push into
    a bounded FIFO queue. RAM is strictly bounded on two axes: the queue holds
    at most a handful of items, and producers block on a shared bytes
    semaphore so in-flight raw payloads never exceed ``_PREFETCH_BYTES_BUDGET``
    regardless of document size. The main coordinator thread consumes from the
    queue and performs CPU normalization, table extraction, and SQLite
    persistence, releasing its byte reservation and periodically invoking
    :func:`defs.runtime.memory.reclaim` so freed C-backed objects (selectolax
    trees, decompressed payloads) are returned to the operating system.
    """
    import queue
    import threading

    pending: list[DocumentLocator] = [
        locator
        for locator in locators
        if doc_id(locator.accession, locator.document_path) not in existing_blobs
        and doc_id(locator.accession, locator.document_path) not in existing_failures
    ]
    if not pending:
        return

    sentinel = object()
    worker_count = max(1, fetch_workers)
    q: queue.Queue = queue.Queue(maxsize=max(worker_count, _PREFETCH_ITEM_CAP))
    bytes_budget = _ByteBudget(_PREFETCH_BYTES_BUDGET)
    locator_iter = iter(pending)
    iter_lock = threading.Lock()

    def producer() -> None:
        while True:
            with iter_lock:
                loc = next(locator_iter, None)
            if loc is None:
                break
            try:
                fetched = _fetch(fetcher, loc)
            except Exception as exc:  # noqa: BLE001
                q.put((loc, None, 0, str(exc) or type(exc).__name__))
                continue
            reserved = len(fetched.payload) if fetched.payload else 0
            if reserved:
                # Block while the in-flight payload budget is exhausted; the
                # consumer releases each reservation after persisting.
                bytes_budget.acquire(reserved)
            q.put((loc, fetched, reserved, None))

    threads = [
        threading.Thread(target=producer, daemon=True) for _ in range(worker_count)
    ]
    for t in threads:
        t.start()

    def waiter() -> None:
        for t in threads:
            t.join()
        q.put(sentinel)

    waiter_thread = threading.Thread(target=waiter, daemon=True)
    waiter_thread.start()

    processed_bytes = 0
    processed_docs = 0
    while True:
        item = q.get()
        if item is sentinel:
            q.task_done()
            break
        loc, fetched, reserved, err = item
        try:
            _persist_fetch_result(
                loc,
                fetched,
                fetcher=fetcher,
                processor=processor,
                executor=executor,
                occurrences_by_doc_id=occurrences_by_doc_id,
                existing_blobs=existing_blobs,
                existing_failures=existing_failures,
                chunk_failures=chunk_failures,
                progress=progress,
                error=err,
            )
        finally:
            if reserved:
                bytes_budget.release(reserved)
            item = None
            loc = None
            fetched = None
            err = None
            processed_bytes += reserved
            processed_docs += 1
            if (
                processed_bytes >= _RECLAIM_BYTES_THRESHOLD
                or processed_docs >= _RECLAIM_DOCS_THRESHOLD
            ):
                reclaim()
                processed_bytes = 0
                processed_docs = 0
            q.task_done()

    waiter_thread.join()


__all__ = [
    "ArchiveFetcher",
    "ChunkFailure",
    "ChunkResult",
    "_run_pipelined_acquisitions",
]
