"""Acquire one isolated webpage chunk and publish its SQLite records."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, runtime_checkable

from defs.sql import DoNothing, SqlDialect, insert_values, make_sql_executor

from .schemas import (
    COMMITTED_CHUNKS_TABLE,
    DOCUMENT_BLOBS_TABLE,
    FILING_OCCURRENCES_TABLE,
    CommittedChunk,
    DocumentLocator,
    FetchResult,
    FilingOccurrence,
    build_blob,
    create_chunk_schema,
)


@runtime_checkable
class ArchiveFetcher(Protocol):
    """Fetcher used by a worker; implementations must be deterministic per locator."""

    def fetch(self, locator: DocumentLocator) -> FetchResult | bytes | None: ...


@dataclass(frozen=True, slots=True)
class ChunkFailure:
    """A locator that could not be stored, including its fetch status."""

    locator: DocumentLocator
    status: str
    error: str


@dataclass(frozen=True, slots=True)
class ChunkResult:
    """Summary of a completed chunk database."""

    chunk_id: str
    worker_id: str
    path: Path
    locator_count: int
    fetched_count: int
    occurrence_count: int
    blob_count: int
    failures: tuple[ChunkFailure, ...]
    audit: CommittedChunk

    @property
    def succeeded(self) -> bool:
        return not self.failures


def _occurrence(value: FilingOccurrence | Mapping[str, object]) -> FilingOccurrence:
    if isinstance(value, FilingOccurrence):
        return value
    return FilingOccurrence.from_row(dict(value))


def _fetch(fetcher: ArchiveFetcher, locator: DocumentLocator) -> FetchResult:
    result = fetcher.fetch(locator)
    if isinstance(result, FetchResult):
        return result
    if isinstance(result, bytes):
        return FetchResult(locator=locator, payload=result, status="ok")
    if result is None:
        return FetchResult(locator=locator, payload=None, status="missing")
    raise TypeError("ArchiveFetcher.fetch must return FetchResult, bytes, or None")


def process_chunk(
    chunk_id: str,
    worker_id: str,
    locators: Sequence[DocumentLocator],
    occurrences: Sequence[FilingOccurrence | Mapping[str, object]],
    fetcher: ArchiveFetcher,
    output_path: str | Path,
) -> ChunkResult:
    """Fetch locators once and write a self-contained SQLite chunk.

    Locator de-duplication is by ``locator_key``. Occurrences are associated by
    accession and document path, which is the identity shared by the phase
    locator and schema records. Fetch errors are reported and do not prevent
    successful records from being committed.
    """
    if not chunk_id or not worker_id:
        raise ValueError("chunk_id and worker_id are required")

    path = Path(output_path)
    normalized_occurrences = tuple(_occurrence(row) for row in occurrences)
    unique_locators: list[DocumentLocator] = []
    seen_keys: set[str] = set()
    for locator in locators:
        if locator.locator_key not in seen_keys:
            seen_keys.add(locator.locator_key)
            unique_locators.append(locator)

    failures: list[ChunkFailure] = []
    successful: dict[str, object] = {}
    seen_occurrence_ids: set[str] = set()
    for locator in unique_locators:
        try:
            fetched = _fetch(fetcher, locator)
        except (OSError, RuntimeError, TypeError, ValueError) as exc:
            failures.append(
                ChunkFailure(locator, "failed", str(exc) or type(exc).__name__)
            )
            continue
        if fetched.status != "ok" or fetched.payload is None:
            failures.append(
                ChunkFailure(locator, fetched.status, fetched.error or fetched.status)
            )
            continue
        successful[(locator.accession, locator.document_path)] = build_blob(
            locator.accession, locator.document_path, fetched.payload
        )

    successful_doc_ids = {blob.doc_id for blob in successful.values()}
    stored_occurrences_list: list[FilingOccurrence] = []
    for occurrence in normalized_occurrences:
        if occurrence.doc_id not in successful_doc_ids:
            continue
        if occurrence.occurrence_id in seen_occurrence_ids:
            continue
        seen_occurrence_ids.add(occurrence.occurrence_id)
        stored_occurrences_list.append(occurrence)
    stored_occurrences = tuple(stored_occurrences_list)
    blobs = tuple(successful.values())
    audit = CommittedChunk(
        chunk_id=chunk_id,
        record_count=len(stored_occurrences),
        worker_id=worker_id,
        committed_at=datetime.now(UTC).isoformat(),
    )

    path.parent.mkdir(parents=True, exist_ok=True)
    # The shared factory treats a non-existent path as an in-memory target.
    path.touch(exist_ok=True)
    executor = make_sql_executor(path, dialect=SqlDialect.SQLITE)
    try:
        create_chunk_schema(executor)
        statements = [
            insert_values(
                DOCUMENT_BLOBS_TABLE,
                [blob.to_row() for blob in blobs],
                on_conflict=DoNothing(),
            )
            for blob in blobs
        ]
        statements.extend(
            insert_values(
                FILING_OCCURRENCES_TABLE,
                occurrence.to_row(),
                on_conflict=DoNothing(),
            )
            for occurrence in stored_occurrences
        )
        statements.append(
            insert_values(
                COMMITTED_CHUNKS_TABLE,
                audit.to_row(),
                on_conflict=DoNothing(),
            )
        )
        executor.transaction(
            tuple(executor.compiler.compile(statement) for statement in statements)
        )
    finally:
        executor.close()

    return ChunkResult(
        chunk_id=chunk_id,
        worker_id=worker_id,
        path=path,
        locator_count=len(unique_locators),
        fetched_count=len(successful),
        occurrence_count=len(stored_occurrences),
        blob_count=len(blobs),
        failures=tuple(failures),
        audit=audit,
    )


def worker(*args, **kwargs) -> ChunkResult:
    """Compatibility entry point for callers naming the operation ``worker``."""
    return process_chunk(*args, **kwargs)


__all__ = ["ArchiveFetcher", "ChunkFailure", "ChunkResult", "process_chunk", "worker"]
