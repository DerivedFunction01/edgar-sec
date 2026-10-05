"""Chunk acquisition and the process pool that runs chunks.

The chunk Parquet file *is* the resumability record — there is no committed ledger.
The fetcher ships by value (paths, never a connection) because a ``sqlite3``
connection cannot cross a process boundary.
"""

from __future__ import annotations

import json
import logging
import os
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from edgar_sec.domain.document.models import (
    DocumentLocator,
    FilingOccurrence,
    derive_document_locator_key,
    derive_occurrence_id,
)
from edgar_sec.foundation.hashing import sha256_text
from edgar_sec.foundation.runtime.memory import reclaim
from edgar_sec.foundation.runtime.resources import (
    RuntimeResourceProfile,
    auto_worker_count,
    derive_resources,
)
from edgar_sec.foundation.runtime.settings import resolve_runtime_settings
from edgar_sec.infra.storage.atomic import atomic_write_json
from edgar_sec.infra.storage.parquet import StagedParquetWriter, read_parquet_table
from edgar_sec.pipelines.document_storage.checkpoint import (
    DOCUMENT_SNAPSHOT_SCHEMA,
    validate_chunk_snapshot,
)
from edgar_sec.pipelines.document_storage.fetching import ArchiveFetcher
from edgar_sec.pipelines.document_storage.paths import chunk_checkpoint_path
from edgar_sec.pipelines.document_storage.processor import (
    DocumentProcessor,
    FilingProcessor,
    ProcessedDocument,
)

log = logging.getLogger("document_storage.worker")

#: Documents processed between heap reclamations. Bounded rather than per-chunk
#: because chunk size varies: a small chunk should not pay for a full GC cycle.
RECLAIM_INTERVAL = 64

WORKER_SCHEMA_VERSION = 1


class ChunkError(RuntimeError):
    """A chunk could not be processed."""


@dataclass(frozen=True, slots=True)
class DelegationTarget:
    """A stub decision a worker observed, for the delegation pass to resolve.

    Only the target's identity travels; exhibits are fetched in that pass.
    """

    document_locator_key: str
    document_path: str
    target_exhibit: str


@dataclass(frozen=True, slots=True)
class ChunkResult:
    """Outcome of processing one chunk."""

    chunk_id: str
    worker_id: str
    output_path: Path
    document_count: int
    normalized_count: int
    failed_count: int
    missing_count: int
    occurrences: int
    processor_fingerprint: str
    payload_sha256: str
    delegations: tuple[DelegationTarget, ...] = ()

    @property
    def ok(self) -> bool:
        return self.failed_count == 0 and self.missing_count == 0


def is_chunk_complete(
    chunks_dir: Path,
    chunk_id: str,
    *,
    processor_fingerprint: str,
) -> bool:
    """Return whether a chunk validates and was written by the current processor.

    Another processor's chunk is not reusable: mixing two text conventions into one
    snapshot is worse than recomputing.
    """
    path = chunk_checkpoint_path(chunks_dir, chunk_id)
    if not path.is_file():
        return False
    try:
        validate_chunk_snapshot(path)
    except (ValueError, FileNotFoundError, OSError) as exc:
        log.info("chunk %s checkpoint is unusable: %s", chunk_id, exc)
        return False
    return chunk_fingerprint(path) == processor_fingerprint


def _unique_locators(
    locators: Sequence[DocumentLocator],
) -> list[DocumentLocator]:
    """Deduplicate locators by key, preserving order for stable rows."""
    seen: set[str] = set()
    unique: list[DocumentLocator] = []
    for locator in locators:
        if locator.document_locator_key in seen:
            continue
        seen.add(locator.document_locator_key)
        unique.append(locator)
    return unique


def _build_snapshot_batch(
    occurrences: Sequence[FilingOccurrence],
    *,
    raw_payload: bytes,
    norm_text: str,
    status: str,
    error: str | None,
) -> dict[str, list[Any]]:
    """Assemble a columnar batch dictionary conforming to DOCUMENT_SNAPSHOT_SCHEMA."""
    occurrence_ids: list[str] = []
    source_ciks: list[str] = []
    accessions: list[str] = []
    document_paths: list[str] = []
    document_locator_keys: list[str] = []
    blob_hashes: list[str] = []
    forms: list[str] = []
    filing_dates: list[str] = []
    raw_payloads: list[bytes] = []
    byte_sizes: list[int] = []
    norm_texts: list[str] = []
    status_list: list[str] = []
    error_list: list[str | None] = []

    byte_size = len(raw_payload)
    for occ in occurrences:
        occurrence_ids.append(occ.occurrence_id)
        source_ciks.append(occ.source_cik.to_10digit())
        accessions.append(str(occ.accession))
        document_paths.append(occ.document_path)
        doc_key = derive_document_locator_key(str(occ.accession), occ.document_path)
        document_locator_keys.append(doc_key)
        blob_hashes.append(occ.doc_id)
        forms.append(occ.form)
        filing_dates.append(occ.filing_date)
        raw_payloads.append(raw_payload)
        byte_sizes.append(byte_size)
        norm_texts.append(norm_text)
        status_list.append(status)
        error_list.append(error)

    return {
        "occurrence_id": occurrence_ids,
        "source_cik": source_ciks,
        "accession": accessions,
        "document_path": document_paths,
        "document_locator_key": document_locator_keys,
        "blob_hash": blob_hashes,
        "form": forms,
        "filing_date": filing_dates,
        "raw_payload": raw_payloads,
        "byte_size": byte_sizes,
        "normalized_text": norm_texts,
        "status": status_list,
        "error_message": error_list,
    }


def process_chunk(
    chunk_id: str,
    worker_id: str,
    locators: Sequence[DocumentLocator],
    occurrences: Sequence[FilingOccurrence],
    *,
    fetcher: ArchiveFetcher,
    processor: DocumentProcessor | None = None,
    chunks_dir: Path,
    profile: RuntimeResourceProfile | None = None,
    payload_sink: Callable[[DocumentLocator, bytes], None] | None = None,
) -> ChunkResult:
    """Fetch and normalize one chunk, publishing it as a Parquet checkpoint.

    Streams each document straight into a staging file, so raw bytes and intermediate
    text leave memory immediately.
    """
    if not chunk_id or not worker_id:
        raise ChunkError("chunk_id and worker_id are required")

    effective_processor = processor if processor is not None else FilingProcessor()
    fingerprint = getattr(
        effective_processor, "processor_fingerprint", "custom:unspecified"
    )
    output_path = chunk_checkpoint_path(chunks_dir, chunk_id)
    unique = _unique_locators(locators)

    by_key: dict[str, list[FilingOccurrence]] = {}
    for occurrence in occurrences:
        by_key.setdefault(occurrence.doc_id, []).append(occurrence)

    expanded_occurrences = _expand_occurrences(unique, by_key, {})
    total_occurrences = len(expanded_occurrences)

    delegations_file = output_path.with_name(f"{output_path.name}.tmp.delegations.json")
    delegations: list[DelegationTarget] = []
    if delegations_file.is_file():
        try:
            stored = json.loads(delegations_file.read_text(encoding="utf-8"))
            delegations = [
                DelegationTarget(
                    document_locator_key=d["document_locator_key"],
                    document_path=d["document_path"],
                    target_exhibit=d["target_exhibit"],
                )
                for d in stored
            ]
        except (ValueError, KeyError, OSError):
            delegations = []

    with StagedParquetWriter(
        output_path,
        schema=DOCUMENT_SNAPSHOT_SCHEMA,
        id_column="occurrence_id",
    ) as writer:
        existing_ids = writer.get_existing_ids()

        for index, locator in enumerate(unique):
            occ_list = by_key.get(locator.document_locator_key)
            if not occ_list:
                occ_list = [_synthetic_occurrence(locator)]

            if existing_ids and all(
                occ.occurrence_id in existing_ids for occ in occ_list
            ):
                continue

            result = fetcher.fetch(locator)
            if not result.ok:
                batch = _build_snapshot_batch(
                    occ_list,
                    raw_payload=b"",
                    norm_text="",
                    status="missing",
                    error=result.error or "payload unavailable",
                )
                writer.write_batch(batch)
                continue

            assert result.payload is not None  # guaranteed by result.ok
            if payload_sink is not None:
                payload_sink(locator, result.payload)

            try:
                processed: ProcessedDocument = effective_processor.process(
                    result.payload, locator
                )
            except Exception as exc:  # noqa: BLE001 - one bad document is not a bad chunk
                log.warning("processing failed for %s: %s", locator.document_path, exc)
                batch = _build_snapshot_batch(
                    occ_list,
                    raw_payload=b"",
                    norm_text="",
                    status="failed",
                    error=str(exc),
                )
                writer.write_batch(batch)
                continue

            decision = processed.decision
            if decision is not None and decision.target_exhibit:
                target = DelegationTarget(
                    document_locator_key=locator.document_locator_key,
                    document_path=locator.document_path,
                    target_exhibit=decision.target_exhibit,
                )
                delegations.append(target)
                try:
                    atomic_write_json(
                        delegations_file,
                        [
                            {
                                "document_locator_key": d.document_locator_key,
                                "document_path": d.document_path,
                                "target_exhibit": d.target_exhibit,
                            }
                            for d in delegations
                        ],
                        canonical=True,
                    )
                except OSError:
                    pass

            batch = _build_snapshot_batch(
                occ_list,
                raw_payload=processed.payload,
                norm_text=processed.text,
                status="ok",
                error=None,
            )
            writer.write_batch(batch)

            if index and index % RECLAIM_INTERVAL == 0:
                reclaim()

        writer.commit(expected_count=total_occurrences)
        _stamp_fingerprint(output_path, fingerprint)

    if delegations_file.is_file():
        try:
            delegations_file.unlink()
        except OSError:
            pass

    # Counts come from the committed table, so they are deterministic across restarts
    # and reflect the chunk's total rather than this pass.
    status_by_doc: dict[str, str] = {}
    if total_occurrences > 0:
        table = read_parquet_table(
            output_path, columns=["document_locator_key", "status"]
        )
        for doc_key, status in zip(
            table.column("document_locator_key").to_pylist(),
            table.column("status").to_pylist(),
            strict=False,
        ):
            status_by_doc[doc_key] = status

    counts = Counter(status_by_doc.values())
    normalized = counts.get("ok", 0)
    failed = counts.get("failed", 0)
    missing = counts.get("missing", 0)

    return ChunkResult(
        chunk_id=chunk_id,
        worker_id=worker_id,
        output_path=output_path,
        document_count=len(unique),
        normalized_count=normalized,
        failed_count=failed,
        missing_count=missing,
        occurrences=total_occurrences,
        processor_fingerprint=fingerprint,
        payload_sha256=sha256_text(
            f"{chunk_id}:{normalized}:{failed}:{missing}:{len(unique)}"
        ),
        delegations=tuple(delegations),
    )


def document_key_of(occurrence: FilingOccurrence) -> str:
    """Return the content-addressed key an occurrence's document is stored under."""
    return derive_document_locator_key(
        str(occurrence.accession), occurrence.document_path
    )


def _expand_occurrences(
    locators: Sequence[DocumentLocator],
    by_key: Mapping[str, list[FilingOccurrence]],
    processed_by_key: Mapping[str, str],
) -> list[FilingOccurrence]:
    """Pair each locator with the provenance rows that reference it.

    An undescribed locator and a document that failed to process both still get a row.
    """
    expanded: list[FilingOccurrence] = []
    for locator in locators:
        matches = by_key.get(locator.document_locator_key)
        if not matches:
            matches = [_synthetic_occurrence(locator)]
        expanded.extend(matches)
    _ = processed_by_key
    return expanded


def _synthetic_occurrence(locator: DocumentLocator) -> FilingOccurrence:
    """Build the provenance row for a locator the catalog did not describe."""
    from edgar_sec.domain.identity import Cik

    document_key = locator.document_locator_key
    return FilingOccurrence(
        occurrence_id=derive_occurrence_id(
            locator.source_cik or "0",
            str(locator.accession),
            locator.document_path,
        ),
        source_cik=Cik.from_raw(locator.source_cik or "0"),
        accession=locator.accession,
        document_path=locator.document_path,
        form=locator.form or "",
        filing_date="",
        report_date=None,
        doc_id=document_key,
    )


def key_of(locator: DocumentLocator) -> str:
    """Return the content hash a locator's payload is stored under."""
    return derive_document_locator_key(str(locator.accession), locator.document_path)


def _stamp_fingerprint(path: Path, fingerprint: str) -> None:
    """Record the producing processor beside the checkpoint, not in its schema.

    Without it a completed chunk cannot be matched against the processor reusing it.
    """
    sidecar = path.with_suffix(".fingerprint")
    sidecar.write_text(fingerprint, encoding="utf-8")


def chunk_fingerprint(path: Path) -> str | None:
    """Read the processor fingerprint stamped on a checkpoint, if any."""
    sidecar = Path(path).with_suffix(".fingerprint")
    if not sidecar.is_file():
        return None
    return sidecar.read_text(encoding="utf-8").strip() or None


def _fingerprint_matches(path: Path, expected: str) -> bool:
    return chunk_fingerprint(path) == expected


def resolved_worker_count(
    profile: RuntimeResourceProfile | None = None, requested: int | None = None
) -> int:
    """Resolve the worker count from cgroup-aware resources, never raw CPU count.

    Budgets come from the settings registry, so an operator's MiB override is honoured.
    """
    if requested is not None and requested > 0:
        return requested
    resolved = profile if profile is not None else derive_resources()
    settings = resolve_runtime_settings()
    return auto_worker_count(
        resolved.available_memory_bytes,
        worker_memory_mib=settings.worker_memory_mib,
        safety_fraction=settings.worker_memory_safety,
    )


def _run_one(task: dict[str, Any]) -> ChunkResult:
    """Execute one chunk in a pool worker. Module-level so it is picklable."""
    return process_chunk(
        task["chunk_id"],
        task["worker_id"],
        task["locators"],
        task["occurrences"],
        fetcher=task["fetcher"],
        processor=task["processor"],
        chunks_dir=task["chunks_dir"],
        profile=task.get("profile"),
    )


def process_chunks(
    chunk_ids: Sequence[str],
    locators_by_chunk: Mapping[str, Sequence[DocumentLocator]],
    occurrences_by_chunk: Mapping[str, Sequence[FilingOccurrence]],
    *,
    fetcher: ArchiveFetcher,
    processor: DocumentProcessor | None = None,
    chunks_dir: Path,
    workers: int | None = None,
    profile: RuntimeResourceProfile | None = None,
    payload_sink: Callable[[DocumentLocator, bytes], None] | None = None,
) -> tuple[ChunkResult, ...]:
    """Process every chunk not already published, returning all chunk results.

    A skipped chunk's result is reconstructed from its checkpoint, so callers see one
    uniform list either way.
    """
    effective_processor = processor if processor is not None else FilingProcessor()
    fingerprint = getattr(
        effective_processor, "processor_fingerprint", "custom:unspecified"
    )
    pending: list[dict[str, Any]] = []
    results: dict[str, ChunkResult] = {}

    for chunk_id in chunk_ids:
        if is_chunk_complete(chunks_dir, chunk_id, processor_fingerprint=fingerprint):
            results[chunk_id] = _skipped_result(
                chunk_id,
                chunks_dir,
                fingerprint,
                len(locators_by_chunk.get(chunk_id, ())),
            )
            continue
        pending.append(
            {
                "chunk_id": chunk_id,
                "worker_id": f"worker-{os.getpid()}",
                "locators": list(locators_by_chunk.get(chunk_id, ())),
                "occurrences": list(occurrences_by_chunk.get(chunk_id, ())),
                "fetcher": fetcher,
                "processor": effective_processor,
                "chunks_dir": Path(chunks_dir),
                "profile": profile,
            }
        )

    if not pending:
        return tuple(results[chunk_id] for chunk_id in chunk_ids)

    resolved = resolved_worker_count(profile, workers)
    if payload_sink is not None or resolved <= 1:
        # A payload sink lives in the parent, and one worker needs no pool.
        for task in pending:
            results[task["chunk_id"]] = process_chunk(
                task["chunk_id"],
                task["worker_id"],
                task["locators"],
                task["occurrences"],
                fetcher=fetcher,
                processor=effective_processor,
                chunks_dir=Path(chunks_dir),
                profile=profile,
                payload_sink=payload_sink,
            )
        return tuple(results[chunk_id] for chunk_id in chunk_ids)

    with ProcessPoolExecutor(
        max_workers=resolved, max_tasks_per_child=RECLAIM_INTERVAL
    ) as pool:
        for result in pool.map(_run_one, pending):
            results[result.chunk_id] = result
            reclaim()

    return tuple(results[chunk_id] for chunk_id in chunk_ids)


def _skipped_result(
    chunk_id: str, chunks_dir: Path, fingerprint: str, document_count: int
) -> ChunkResult:
    path = chunk_checkpoint_path(chunks_dir, chunk_id)
    meta = validate_chunk_snapshot(path)
    return ChunkResult(
        chunk_id=chunk_id,
        worker_id="skipped",
        output_path=path,
        document_count=document_count,
        normalized_count=int(meta["num_rows"]),
        failed_count=0,
        missing_count=0,
        occurrences=int(meta["num_rows"]),
        processor_fingerprint=fingerprint,
        payload_sha256=sha256_text(f"{chunk_id}:skipped"),
    )


__all__ = [
    "RECLAIM_INTERVAL",
    "WORKER_SCHEMA_VERSION",
    "ChunkError",
    "ChunkResult",
    "DelegationTarget",
    "chunk_fingerprint",
    "is_chunk_complete",
    "process_chunk",
    "process_chunks",
    "resolved_worker_count",
]
