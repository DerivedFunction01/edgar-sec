"""Fetch, normalize, and publish one chunk, plus the process pool that runs them.

The execution unit: ``process_chunk`` returns one checkpoint; ``process_chunks``
and ``process_chunk_stream`` drive the pool. Pool sizing is cgroup-aware and
children are recycled to bound heap growth.
"""

from __future__ import annotations

import json
import logging
import os
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import FIRST_COMPLETED, Future, ProcessPoolExecutor, wait
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from edgar_sec.domain.document.models import DocumentLocator, FilingOccurrence
from edgar_sec.foundation.hashing import sha256_text
from edgar_sec.foundation.runtime.memory import reclaim
from edgar_sec.foundation.runtime.resources import (
    RuntimeResourceProfile,
    auto_worker_count,
    derive_resources,
)
from edgar_sec.foundation.runtime.settings import resolve_runtime_settings
from edgar_sec.infra.storage.atomic import atomic_write_json, atomic_write_text
from edgar_sec.infra.storage.parquet import StagedParquetWriter, read_parquet_table
from edgar_sec.pipelines.document_storage.checkpoint import (
    DOCUMENT_SNAPSHOT_SCHEMA,
    _read_delegations,
    _stamp_fingerprint,
    _valid_partial_checkpoint,
    is_chunk_complete,
    validate_chunk_snapshot,
    _write_catalog_delegations,
)
from edgar_sec.pipelines.document_storage.fetching import ArchiveFetcher
from edgar_sec.pipelines.document_storage.occurrences import (
    _expand_occurrences,
    _filing_work,
    _occurrences_by_key,
    _unique_locators,
)
from edgar_sec.pipelines.document_storage.processor import (
    DocumentProcessor,
    FilingProcessor,
)
from edgar_sec.pipelines.document_storage.candidate_recovery import (
    outcome_batch,
    run_candidate_recovery,
)
from edgar_sec.pipelines.document_storage.processing import (
    _build_snapshot_batch,
    _occurrence_report_dates,
    _process_locator,
    _record_delegation,
)
from edgar_sec.pipelines.document_storage.paths import chunk_checkpoint_path
from edgar_sec.pipelines.document_storage.summary import candidate_summary
from edgar_sec.pipelines.document_storage.work_order import (
    ChunkInput,
    DelegationTarget,
    WorkOrder,
)

log = logging.getLogger("document_storage.execution")

#: Documents processed before a pool child is recycled to reclaim heap.
RECLAIM_INTERVAL = 64

#: Schema version carried by worker-written checkpoints; owned here because it is
#: part of the execution contract, not of the merger or the storage paths.
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
    execution_state: str = "fresh"

    @property
    def ok(self) -> bool:
        return self.failed_count == 0 and self.missing_count == 0


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
    catalog_checkpoint: bool = False,
    force_recompute: bool = False,
) -> "ChunkResult":
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

    expanded_occurrences = _expand_occurrences(unique, by_key)
    total_occurrences = len(expanded_occurrences)
    candidate_eligible = 0
    bundle_candidates = 0
    date_unresolved = 0

    delegations_file = output_path.with_name(f"{output_path.name}.tmp.delegations.json")
    temp_fingerprint = output_path.with_name(f"{output_path.name}.tmp.fingerprint")
    delegations: list[DelegationTarget] = []
    resumed_partial = False
    if catalog_checkpoint:
        resumed_partial = (
            not force_recompute
            and _valid_partial_checkpoint(output_path, fingerprint)
            and _read_delegations(delegations_file) is not None
        )
        if not resumed_partial:
            delegations_file.unlink(missing_ok=True)
            temp_fingerprint.unlink(missing_ok=True)
        else:
            delegations = _read_delegations(delegations_file) or []
            atomic_write_text(temp_fingerprint, fingerprint)
    elif delegations_file.is_file():
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
        if catalog_checkpoint and not resumed_partial:
            writer.reset()
            atomic_write_text(temp_fingerprint, fingerprint)
            atomic_write_json(delegations_file, [], canonical=True)
        existing_ids = writer.get_existing_ids()
        seen = set(existing_ids)
        chunk_expected = len(existing_ids)

        for locator in unique:
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
        if catalog_checkpoint:
            _write_catalog_delegations(output_path, chunk_id, fingerprint, delegations)

    if delegations_file.is_file():
        try:
            delegations_file.unlink()
        except OSError:
            pass
    temp_fingerprint.unlink(missing_ok=True)

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
        execution_state="resumed" if resumed_partial else "fresh",
    )


def _skipped_result(
    chunk_id: str,
    chunks_dir: Path,
    fingerprint: str,
    document_count: int,
    candidate_counts: tuple[int, int, int],
) -> "ChunkResult":
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
) -> tuple["ChunkResult", ...]:
    """Process every chunk not already published, returning all chunk results.

    A skipped chunk's result is reconstructed from its checkpoint, so callers see one
    uniform list either way.
    """
    effective_processor = processor if processor is not None else FilingProcessor()
    fingerprint = getattr(
        effective_processor, "processor_fingerprint", "custom:unspecified"
    )
    pending: list[dict[str, Any]] = []
    results: dict[str, "ChunkResult"] = {}

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


def process_chunk_stream(
    work_order: WorkOrder,
    *,
    fetcher: ArchiveFetcher,
    processor: DocumentProcessor | None = None,
    chunks_dir: Path,
    workers: int | None = None,
    profile: RuntimeResourceProfile | None = None,
) -> tuple["ChunkResult", ...]:
    """Process a replayable work order without holding the plan in memory.

    At most ``resolved_worker_count`` chunks are in flight. No chunk is treated as
    complete: this is the fresh-run path.
    """
    effective_processor = processor if processor is not None else FilingProcessor()
    resolved = resolved_worker_count(profile, workers)
    results: list["ChunkResult"] = []

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
        in_flight: dict[Future["ChunkResult"], None] = {}
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


__all__ = [
    "ChunkError",
    "ChunkResult",
    "RECLAIM_INTERVAL",
    "WORKER_SCHEMA_VERSION",
    "process_chunk",
    "process_chunks",
    "process_chunk_stream",
    "resolved_worker_count",
    "_error_batch",
    "_run_one",
    "_skipped_result",
]
