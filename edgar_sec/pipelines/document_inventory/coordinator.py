"""S4 coordinator: bounded in-flight scheduling, chunk commit, and resume.

Owns the broker lifecycle, the process pool, and the pointer-last commit
protocol. The per-accession task lives in ``worker.py``; the broker adapter
lives in ``broker.py``.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Iterator, Sequence
from concurrent.futures import FIRST_COMPLETED, Future, ProcessPoolExecutor, wait
from dataclasses import dataclass
from multiprocessing import get_context
from pathlib import Path
from typing import Any

from edgar_sec.domain.document_inventory.models import IndexWorkItem
from edgar_sec.foundation.runtime.memory import reclaim
from edgar_sec.foundation.runtime.resources import (
    RuntimeResourceProfile,
    derive_resources,
)
from edgar_sec.foundation.runtime.settings import resolve_runtime_settings
from edgar_sec.infra.broker.daemon import managed_broker

from .broker import IndexPageBrokerClient
from .checkpoint import (
    AttemptWriters,
    ChunkValidation,
    REFUSAL_STATUSES,
    RETRYABLE_STATUSES,
    entry_rows,
    finalize_attempt,
    new_attempt_id,
    outcome_row,
    read_entry_rows,
    read_outcome_rows,
    split_retryable,
    validate_committed_chunk,
)
from .paths import InventoryPaths, InventoryRunPaths
from .run_manifest import (
    ChunkIdentity,
    InventoryRunManifest,
    WORK_ORDER_VERSION,
    iter_work_order_chunks,
    read_run_manifest,
    validate_run_manifest,
    write_run_manifest,
)
from .worker import (
    IndexWorkerFailure,
    RECLAIM_INTERVAL,
    _TypedResult,
    _run_task,
)

log = logging.getLogger("document_inventory.coordinator")

#: Socket prefix beside the shared broker socket; run id keeps runs isolated.
SOCKET_PREFIX = "s4-"
MAX_SUMMARY_CHUNKS = 128

__all__ = [
    "ChunkOutcome",
    "RunSummary",
    "run_missing_accessions",
]


def _bounded_results(
    items: Sequence[IndexWorkItem],
    broker: IndexPageBrokerClient,
    workers: int,
    force_refresh: bool,
    pool: ProcessPoolExecutor | None,
) -> Iterator[_TypedResult]:
    """Yield one typed result per item in completion order, bounded by ``workers``.

    At most ``workers`` tasks are in flight and each freed slot is refilled as a
    future completes; a failed future becomes a typed failure for its own accession.
    """
    if pool is None:
        for item in items:
            yield _run_task(item, broker, force_refresh=force_refresh)
            reclaim()
        return

    source = iter(items)
    in_flight: dict[Future[_TypedResult], IndexWorkItem] = {}
    exhausted = False

    def submit_next() -> list[_TypedResult]:
        """Submit one task; on a broken pool, emit typed failures for the rest."""
        nonlocal exhausted
        item = next(source, None)
        if item is None:
            exhausted = True
            return []
        try:
            in_flight[pool.submit(_run_task, item, broker, force_refresh)] = item
            return []
        except Exception as exc:  # noqa: BLE001 - broken pool must not erase siblings
            exhausted = True
            detail = str(exc) or type(exc).__name__
            failures = [IndexWorkerFailure(item.accession, "worker_error", detail)]
            failures.extend(
                IndexWorkerFailure(rest.accession, "worker_error", detail)
                for rest in source
            )
            return failures

    for _ in range(max(1, workers)):
        for failure in submit_next():
            yield failure
        if exhausted:
            break
    while in_flight:
        done, _ = wait(in_flight, return_when=FIRST_COMPLETED)
        for future in done:
            item = in_flight.pop(future)
            try:
                yield future.result()
            except Exception as exc:  # noqa: BLE001
                detail = str(exc) or type(exc).__name__
                yield IndexWorkerFailure(item.accession, "worker_error", detail)
        for _ in range(len(done)):
            for failure in submit_next():
                yield failure
            if exhausted:
                break
        reclaim()


def _write_results(
    writers: AttemptWriters,
    url_by_accession: dict[str, str],
    results: Iterator[_TypedResult],
) -> tuple[int, int]:
    """Stream results into staged Parquet; return (refused, retryable) counts."""
    refused = 0
    retryable = 0
    for result in results:
        row = outcome_row(
            result, index_url=url_by_accession.get(str(result.accession), "")
        )
        writers.add(row, entry_rows(result))
        if row["status"] in REFUSAL_STATUSES:
            refused += 1
        if row["status"] in RETRYABLE_STATUSES:
            retryable += 1
    return refused, retryable


@dataclass(frozen=True, slots=True)
class ChunkOutcome:
    """Result of committing or reusing one chunk attempt."""

    chunk_id: str
    attempt_id: str
    resumed: bool
    outcome_count: int
    entry_count: int
    refusal_count: int


@dataclass(frozen=True, slots=True)
class RunSummary:
    """Run counters and a bounded prefix of per-chunk outcomes."""

    run_id: str
    chunks: tuple[ChunkOutcome, ...]
    resumed_count: int
    committed_count: int
    refusal_count: int
    chunk_count: int
    chunks_truncated: bool


class _RunSummaryCollector:
    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self.chunks: list[ChunkOutcome] = []
        self.resumed_count = 0
        self.committed_count = 0
        self.refusal_count = 0
        self.chunk_count = 0

    def record(self, outcome: ChunkOutcome) -> None:
        self.chunk_count += 1
        self.resumed_count += int(outcome.resumed)
        self.committed_count += int(not outcome.resumed)
        self.refusal_count += outcome.refusal_count
        if len(self.chunks) < MAX_SUMMARY_CHUNKS:
            self.chunks.append(outcome)

    def finish(self) -> RunSummary:
        return RunSummary(
            run_id=self.run_id,
            chunks=tuple(self.chunks),
            resumed_count=self.resumed_count,
            committed_count=self.committed_count,
            refusal_count=self.refusal_count,
            chunk_count=self.chunk_count,
            chunks_truncated=self.chunk_count > len(self.chunks),
        )


def _membership_of(members: Sequence[IndexWorkItem]) -> tuple[str, ...]:
    return tuple(str(item.accession) for item in members)


def _url_index(members: Sequence[IndexWorkItem]) -> dict[str, str]:
    return {str(item.accession): item.index_url for item in members}


def _process_chunk_fresh(
    paths: InventoryRunPaths,
    run: InventoryRunManifest,
    chunk_id: str,
    members: Sequence[IndexWorkItem],
    broker: IndexPageBrokerClient,
    workers: int,
    force_refresh: bool,
    attempt_id: str,
    pool: ProcessPoolExecutor | None,
) -> ChunkOutcome:
    """Fetch every member into a new immutable attempt, then validate and commit."""
    writers = AttemptWriters(paths, chunk_id, attempt_id)
    try:
        refused, _ = _write_results(
            writers,
            _url_index(members),
            _bounded_results(members, broker, workers, force_refresh, pool),
        )
    finally:
        writers.close()
    manifest = finalize_attempt(
        paths, chunk_id, attempt_id, membership=_membership_of(members), run=run
    )
    log.info(
        "committed chunk %s attempt %s (%d outcomes)",
        chunk_id,
        attempt_id,
        manifest.outcomes_rows,
    )
    return ChunkOutcome(
        chunk_id=chunk_id,
        attempt_id=attempt_id,
        resumed=False,
        outcome_count=manifest.outcomes_rows,
        entry_count=manifest.entries_rows,
        refusal_count=refused,
    )


def _process_chunk_retry(
    paths: InventoryRunPaths,
    run: InventoryRunManifest,
    chunk_id: str,
    members: Sequence[IndexWorkItem],
    broker: IndexPageBrokerClient,
    workers: int,
    force_refresh: bool,
    attempt_id: str,
    prior_attempt_id: str,
    pool: ProcessPoolExecutor | None,
) -> ChunkOutcome:
    """Carry prior non-retryable outcomes forward and retry only failed accessions."""
    outcomes = read_outcome_rows(paths, chunk_id, prior_attempt_id)
    entries = read_entry_rows(paths, chunk_id, prior_attempt_id)
    carry, retry_accessions = split_retryable(outcomes)
    retry_items = tuple(
        item for item in members if str(item.accession) in retry_accessions
    )
    entries_by_accession: dict[str, list[dict[str, Any]]] = {}
    for row in entries:
        entries_by_accession.setdefault(str(row.get("accession")), []).append(row)

    refused = 0
    writers = AttemptWriters(paths, chunk_id, attempt_id)
    try:
        for row in carry:
            accession = str(row.get("accession"))
            writers.add(row, entries_by_accession.get(accession, []))
            if row.get("status") in REFUSAL_STATUSES:
                refused += 1
        new_refused, _ = _write_results(
            writers,
            _url_index(members),
            _bounded_results(retry_items, broker, workers, force_refresh, pool),
        )
        refused += new_refused
    finally:
        writers.close()
    manifest = finalize_attempt(
        paths, chunk_id, attempt_id, membership=_membership_of(members), run=run
    )
    log.info(
        "retried chunk %s attempt %s (%d outcomes, %d carried)",
        chunk_id,
        attempt_id,
        manifest.outcomes_rows,
        len(carry),
    )
    return ChunkOutcome(
        chunk_id=chunk_id,
        attempt_id=attempt_id,
        resumed=False,
        outcome_count=manifest.outcomes_rows,
        entry_count=manifest.entries_rows,
        refusal_count=refused,
    )


def _reuse_outcome(
    chunk_id: str, validation: ChunkValidation, refusal_count: int
) -> ChunkOutcome:
    assert validation.attempt_id is not None and validation.manifest is not None
    return ChunkOutcome(
        chunk_id=chunk_id,
        attempt_id=validation.attempt_id,
        resumed=True,
        outcome_count=validation.manifest.outcomes_rows,
        entry_count=validation.manifest.entries_rows,
        refusal_count=refusal_count,
    )


def _decide_chunk(
    paths: InventoryRunPaths,
    run: InventoryRunManifest,
    chunk_id: str,
    identity: Any,
    retry_failures: bool,
) -> tuple[str, str | None, ChunkOutcome | None]:
    """Classify one chunk as skip/retry/fresh without touching the network.

    Returns ``(mode, prior_attempt_id, ready_outcome)``; only ``skip`` carries a
    ready outcome, computed here and discarded after appending.
    """
    validation = validate_committed_chunk(paths, chunk_id, run=run, chunk=identity)
    if not (validation.valid and validation.attempt_id and validation.manifest):
        log.info("chunk %s invalid (%s); recomputing", chunk_id, validation.reason)
        return "fresh", None, None
    rows = read_outcome_rows(paths, chunk_id, validation.attempt_id)
    _, retry = split_retryable(rows)
    refusal_count = sum(1 for row in rows if row.get("status") in REFUSAL_STATUSES)
    if retry and retry_failures:
        return "retry", validation.attempt_id, None
    return "skip", None, _reuse_outcome(chunk_id, validation, refusal_count)


def run_missing_accessions(
    work_order_path: Path | str,
    run_identity: dict[str, Any],
    paths: InventoryRunPaths,
    *,
    http_client: Any | None = None,
    profile: RuntimeResourceProfile | None = None,
    workers: int | None = None,
    retry_failures: bool = False,
) -> RunSummary:
    """Validate the run manifest, then commit every chunk with resume and retry.

    The manifest is checked before any broker call; valid chunks are reused
    without network access. ``retry_failures`` rewrites only retryable chunks.
    """
    work_order_path = Path(work_order_path)
    if work_order_path.resolve() != paths.work_order_path().resolve():
        raise ValueError("work-order path must match the run's centralized path")
    existing = read_run_manifest(paths)
    if existing is None:
        manifest = write_run_manifest(
            paths, work_order_path=work_order_path, **_manifest_kwargs(run_identity)
        )
    else:
        manifest = _validate_existing(existing, work_order_path, run_identity)

    resolved = profile if profile is not None else derive_resources()
    effective_workers = max(
        1, workers if workers is not None and workers > 0 else resolved.workers
    )
    force_refresh = manifest.fetch_mode == "force_refresh"

    if manifest.work_order_rows == 0:
        return RunSummary(manifest.run_id, (), 0, 0, 0, 0, False)
    chunks = iter_work_order_chunks(
        work_order_path,
        chunk_size=manifest.chunk_size,
        work_order_version=manifest.work_order_version,
    )
    return _run_pending(
        chunks,
        paths,
        manifest,
        run_id=manifest.run_id,
        http_client=http_client,
        workers=effective_workers,
        force_refresh=force_refresh,
        retry_failures=retry_failures,
    )


def _run_pending(
    chunks: Iterable[tuple[ChunkIdentity, tuple[IndexWorkItem, ...]]],
    paths: InventoryRunPaths,
    manifest: InventoryRunManifest,
    *,
    run_id: str,
    http_client: Any | None,
    workers: int,
    force_refresh: bool,
    retry_failures: bool,
) -> RunSummary:
    """Process a Parquet work order one bounded chunk at a time."""
    socket_path = InventoryPaths(paths.artifacts_root).broker_socket_path(
        f"{SOCKET_PREFIX}{paths.run_id}"
    )
    socket_path.parent.mkdir(parents=True, exist_ok=True)
    summary = _RunSummaryCollector(run_id)

    with managed_broker(
        socket_path,
        http_client=http_client,
        max_connections=workers,
    ):
        broker = IndexPageBrokerClient(socket_path)
        pool_cm = (
            ProcessPoolExecutor(
                max_workers=workers,
                max_tasks_per_child=RECLAIM_INTERVAL,
                mp_context=get_context("spawn"),
            )
            if workers > 1
            else None
        )
        try:
            for identity, members in chunks:
                chunk_id = identity.chunk_id
                mode, prior_id, ready = _decide_chunk(
                    paths,
                    manifest,
                    chunk_id,
                    identity,
                    retry_failures,
                )
                if ready is not None:
                    summary.record(ready)
                    continue
                if mode == "retry" and prior_id is not None:
                    outcome = _process_chunk_retry(
                        paths,
                        manifest,
                        chunk_id,
                        members,
                        broker,
                        workers,
                        force_refresh,
                        new_attempt_id(),
                        prior_id,
                        pool_cm,
                    )
                else:
                    outcome = _process_chunk_fresh(
                        paths,
                        manifest,
                        chunk_id,
                        members,
                        broker,
                        workers,
                        force_refresh,
                        new_attempt_id(),
                        pool_cm,
                    )
                summary.record(outcome)
                reclaim()
        finally:
            if pool_cm is not None:
                pool_cm.shutdown(wait=True)
    return summary.finish()


def _manifest_kwargs(run_identity: dict[str, Any]) -> dict[str, Any]:
    return {
        "parent_snapshot_id": str(run_identity.get("parent_snapshot_id", "")),
        "canonical_cohort_id": str(run_identity.get("canonical_cohort_id", "")),
        "source_identity": str(run_identity.get("source_identity", "")),
        "parser_version": str(run_identity.get("parser_version", "")),
        "chunk_size": int(
            run_identity.get("chunk_size")
            or resolve_runtime_settings().default_chunk_size
        ),
        "refresh_mode": str(run_identity.get("refresh_mode", "normal")),
        "fetch_mode": str(run_identity.get("fetch_mode", "live")),
        "fixture_id": run_identity.get("fixture_id"),
        "work_order_version": str(
            run_identity.get("work_order_version") or WORK_ORDER_VERSION
        ),
    }


def _validate_existing(
    existing: InventoryRunManifest,
    work_order_path: Path,
    run_identity: dict[str, Any],
) -> InventoryRunManifest:
    kwargs = _manifest_kwargs(run_identity)
    return validate_run_manifest(
        existing,
        run_id=existing.run_id,
        parent_snapshot_id=kwargs["parent_snapshot_id"],
        canonical_cohort_id=kwargs["canonical_cohort_id"],
        source_identity=kwargs["source_identity"],
        parser_version=kwargs["parser_version"],
        chunk_size=kwargs["chunk_size"],
        refresh_mode=kwargs["refresh_mode"],
        fetch_mode=kwargs["fetch_mode"],
        fixture_id=kwargs["fixture_id"],
        work_order_path=work_order_path,
        work_order_version=kwargs["work_order_version"],
    )
