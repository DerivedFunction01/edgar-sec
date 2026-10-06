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
from concurrent.futures import FIRST_COMPLETED, Future, ProcessPoolExecutor, wait
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path
from typing import Any

from edgar_sec.domain.document.acquisition import AcquiredSubmission
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
from edgar_sec.pipelines.document_storage.candidates import (
    CandidateDecision,
    candidate_for,
)
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
from edgar_sec.pipelines.document_storage.work_order import ChunkInput, WorkOrder
from edgar_sec.pipelines.document_storage.candidate_recovery import (
    CandidateOutcome,
    outcome_batch,
    run_candidate_recovery,
)
from edgar_sec.pipelines.document_storage.processing import (
    _build_snapshot_batch,
    _occurrence_report_dates,
    _process_locator,
    _record_delegation,
)
from edgar_sec.pipelines.document_storage.work_order import (
    DelegationTarget,
    FilingWork,
)

log = logging.getLogger("document_storage.worker")

#: Documents processed between heap reclamations. Bounded rather than per-chunk
#: because chunk size varies: a small chunk should not pay for a full GC cycle.
RECLAIM_INTERVAL = 64

WORKER_SCHEMA_VERSION = 1


class ChunkError(RuntimeError):
    """A chunk could not be processed."""


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
    candidate_eligible_count: int = 0
    bundle_candidate_count: int = 0
    candidate_date_unresolved_count: int = 0
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


def _occurrences_by_key(
    occurrences: Sequence[FilingOccurrence],
) -> dict[str, list[FilingOccurrence]]:
    """Group provenance rows by the locator key they reference."""
    by_key: dict[str, list[FilingOccurrence]] = {}
    for occurrence in occurrences:
        by_key.setdefault(occurrence.doc_id, []).append(occurrence)
    return by_key


def _filing_work(
    locator: DocumentLocator, by_key: Mapping[str, list[FilingOccurrence]]
) -> FilingWork:
    """Build one work record, so the candidate gate sees the catalog's filing date."""
    occurrences = by_key.get(locator.document_locator_key) or [
        _synthetic_occurrence(locator)
    ]
    filing_date, candidate = candidate_for(locator, occurrences)
    return FilingWork(
        locator=locator,
        occurrences=tuple(occurrences),
        filing_date=filing_date,
        candidate=candidate,
    )


def candidate_summary(
    locators: Sequence[DocumentLocator],
    occurrences: Sequence[FilingOccurrence],
) -> tuple[int, int, int]:
    """Return ``(window_eligible, bundle_candidate, unresolved_date)`` over one chunk.

    Derived from the plan's own inputs rather than from a checkpoint, so a resumed chunk
    reports what a fresh one would; co-filer occurrences count on their shared locator once.
    """
    by_key = _occurrences_by_key(occurrences)
    eligible = 0
    candidates = 0
    unresolved = 0
    for locator in _unique_locators(locators):
        filing_date, decision = candidate_for(
            locator, by_key.get(locator.document_locator_key) or ()
        )
        eligible += int(decision.window_eligible)
        candidates += int(decision.is_bundle_candidate)
        unresolved += int(filing_date is None)
    return eligible, candidates, unresolved


def _error_batch(
    occurrences: Sequence[FilingOccurrence],
    status: str,
    error: str,
    report_dates: Mapping[str, str | None] | None = None,
) -> dict[str, list]:
    """Assemble an error batch with no retained payload."""
    return _build_snapshot_batch(
        occurrences,
        raw_payload=b"",
        norm_text="",
        status=status,
        error=error,
        report_dates=report_dates,
    )


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

    by_key = _occurrences_by_key(occurrences)

    expanded_occurrences = _expand_occurrences(unique, by_key, {})
    total_occurrences = len(expanded_occurrences)
    candidate_eligible = 0
    bundle_candidates = 0
    date_unresolved = 0

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
        seen = set(existing_ids)
        chunk_expected = len(existing_ids)

        for index, locator in enumerate(unique):
            work = _filing_work(locator, by_key)
            candidate_eligible += int(work.candidate.window_eligible)
            bundle_candidates += int(work.candidate.is_bundle_candidate)
            date_unresolved += int(work.filing_date is None)

            if existing_ids and all(
                occ.occurrence_id in existing_ids for occ in work.occurrences
            ):
                continue

            if work.candidate.is_bundle_candidate:
                # Candidate recovery: bundle-first, one outcome per emitted row.
                # Track occurrence IDs seen in this chunk (resumption + in-chunk
                # dedup) so repeated recovered identities do not emit duplicates.
                try:
                    outcomes, candidate_delegations = run_candidate_recovery(
                        work.locator, work.occurrences, fetcher, effective_processor
                    )
                except Exception as exc:  # noqa: BLE001
                    log.warning(
                        "candidate recovery failed for %s: %s",
                        locator.document_path,
                        exc,
                    )
                    fresh = tuple(
                        occ for occ in work.occurrences if occ.occurrence_id not in seen
                    )
                    if fresh:
                        writer.write_batch(
                            _error_batch(
                                fresh,
                                "failed",
                                str(exc),
                                report_dates=_occurrence_report_dates(fresh),
                            )
                        )
                        seen.update(occ.occurrence_id for occ in fresh)
                        chunk_expected += len(fresh)
                    continue
                for outcome in outcomes:
                    if outcome.occurrence_id in seen:
                        continue  # already persisted; do not emit duplicates.
                    seen.add(outcome.occurrence_id)
                    chunk_expected += 1
                    batch = outcome_batch(outcome)
                    writer.write_batch(batch)
                    if outcome.status == "ok" and payload_sink is not None:
                        payload_sink(work.locator, outcome.raw_payload)
                    if outcome.status == "ok":
                        for dk, dp, te in candidate_delegations:
                            _record_delegation(
                                delegations, delegations_file, dk, dp, te
                            )
            else:
                fresh = tuple(
                    occ for occ in work.occurrences if occ.occurrence_id not in seen
                )
                if not fresh:
                    continue
                work = replace(work, occurrences=fresh)
                _process_locator(
                    locator,
                    work,
                    fetcher,
                    effective_processor,
                    payload_sink,
                    delegations,
                    delegations_file,
                    writer,
                )
                chunk_expected += len(work.occurrences)
                seen.update(occ.occurrence_id for occ in work.occurrences)

        writer.commit(expected_count=chunk_expected)
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
        candidate_eligible_count=candidate_eligible,
        bundle_candidate_count=bundle_candidates,
        candidate_date_unresolved_count=date_unresolved,
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
        locators = locators_by_chunk.get(chunk_id, ())
        if is_chunk_complete(chunks_dir, chunk_id, processor_fingerprint=fingerprint):
            results[chunk_id] = _skipped_result(
                chunk_id,
                chunks_dir,
                fingerprint,
                len(locators),
                candidate_summary(locators, occurrences_by_chunk.get(chunk_id, ())),
            )
            continue
        pending.append(
            {
                "chunk_id": chunk_id,
                "worker_id": f"worker-{os.getpid()}",
                "locators": list(locators),
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
    chunk_id: str,
    chunks_dir: Path,
    fingerprint: str,
    document_count: int,
    candidate_counts: tuple[int, int, int],
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
        candidate_eligible_count=candidate_counts[0],
        bundle_candidate_count=candidate_counts[1],
        candidate_date_unresolved_count=candidate_counts[2],
    )


def process_chunk_stream(
    work_order: WorkOrder,
    *,
    fetcher: ArchiveFetcher,
    processor: DocumentProcessor | None = None,
    chunks_dir: Path,
    workers: int | None = None,
    profile: RuntimeResourceProfile | None = None,
) -> tuple[ChunkResult, ...]:
    """Process a replayable work order without holding the plan in memory.

    At most ``resolved_worker_count`` chunks are in flight. No chunk is treated as
    complete: this is the fresh-run path.
    """
    effective_processor = processor if processor is not None else FilingProcessor()
    resolved = resolved_worker_count(profile, workers)
    results: list[ChunkResult] = []

    def task_for(chunk: ChunkInput, worker_id: str) -> dict[str, Any]:
        return {
            "chunk_id": chunk.chunk_id,
            "worker_id": worker_id,
            "locators": list(chunk.locators),
            "occurrences": list(chunk.occurrences),
            "fetcher": fetcher,
            "processor": effective_processor,
            "chunks_dir": Path(chunks_dir),
            "profile": profile,
        }

    if resolved <= 1:
        for chunk in work_order.iter_chunks():
            results.append(
                process_chunk(
                    chunk.chunk_id,
                    f"worker-{os.getpid()}",
                    list(chunk.locators),
                    list(chunk.occurrences),
                    fetcher=fetcher,
                    processor=effective_processor,
                    chunks_dir=Path(chunks_dir),
                    profile=profile,
                )
            )
            reclaim()
        return tuple(results)

    worker_id = f"worker-{os.getpid()}"
    with ProcessPoolExecutor(
        max_workers=resolved, max_tasks_per_child=RECLAIM_INTERVAL
    ) as pool:
        source = work_order.iter_chunks()
        in_flight: dict[Future[ChunkResult], None] = {}
        for _ in range(resolved):
            chunk = next(source, None)
            if chunk is None:
                break
            in_flight[pool.submit(_run_one, task_for(chunk, worker_id))] = None
        while in_flight:
            done, _ = wait(in_flight, return_when=FIRST_COMPLETED)
            for future in done:
                in_flight.pop(future)
                results.append(future.result())
                reclaim()
            for _ in range(len(done)):
                chunk = next(source, None)
                if chunk is None:
                    break
                in_flight[pool.submit(_run_one, task_for(chunk, worker_id))] = None

    return tuple(sorted(results, key=lambda result: result.chunk_id))


__all__ = [
    "RECLAIM_INTERVAL",
    "WORKER_SCHEMA_VERSION",
    "ChunkError",
    "ChunkResult",
    "DelegationTarget",
    "FilingWork",
    "candidate_summary",
    "chunk_fingerprint",
    "is_chunk_complete",
    "process_chunk",
    "process_chunk_stream",
    "process_chunks",
    "resolved_worker_count",
]
