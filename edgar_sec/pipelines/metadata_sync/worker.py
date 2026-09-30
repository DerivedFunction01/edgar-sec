"""Resumable chunk execution.

One chunk is the unit of work and of checkpointing. Within a chunk, CIKs are
fetched concurrently on threads: the shared HTTP client and its SQLite cache
are both thread-safe, the work is network-bound rather than CPU-bound, and
DuckDB is confined to the coordinator, so nothing here needs process isolation.

Every requested CIK produces exactly one row, including failures, so completion
is determinable from the data rather than from queue state. A chunk's CIKs come
from the plan's roster range, so the same call works against a plan this process
planned and a plan it was handed as a copied bundle.
"""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

from edgar_sec.domain.submissions.schemas import (
    SUBMISSION_METADATA_SCHEMA,
    TERMINAL_STATUSES,
)
from edgar_sec.engine.submissions.builder import (
    build_submission_table,
    normalize_submissions,
)
from edgar_sec.foundation.runtime.memory import reclaim
from edgar_sec.infra.storage.parquet import StagedParquetWriter, read_parquet_table

from .checkpoints import inspect_chunk
from .paths import RunPaths
from .planner import Plan, utc_now_iso
from .sec_client import CikFetchResult, SubmissionsClient

RECLAIM_INTERVAL = 64

__all__ = [
    "ChunkResult",
    "normalize_one_cik",
    "resolve_workers",
    "run_chunk",
    "run_chunk_ids",
]


def resolve_workers(workers: int | None = None) -> int:
    """Resolve the worker count, deriving it from the machine when unset."""
    if workers is not None and workers > 0:
        return workers
    from edgar_sec.foundation.runtime.resources import derive_resources

    return max(1, derive_resources().workers)


@dataclass(slots=True)
class ChunkResult:
    """Outcome of executing one chunk."""

    chunk_id: int
    path: str
    row_count: int
    skipped_existing: bool = False
    statuses: dict[str, int] = field(default_factory=dict)
    historical_files: int = 0


def normalize_one_cik(
    client: SubmissionsClient,
    cik_padded: str,
    *,
    input_name: str,
    snapshot_id: str,
    input_fingerprint: str,
    chunk_id: int,
    fetched_at: str | None = None,
) -> tuple[dict[str, Any], CikFetchResult]:
    """Fetch and normalize one CIK into a canonical row dict."""
    stamp = fetched_at or utc_now_iso()
    result = client.fetch_cik(cik_padded)
    row = normalize_submissions(
        result.payload if result.payload is not None else {},
        cik_padded=cik_padded,
        input_name=input_name,
        snapshot_id=snapshot_id,
        fetched_at=stamp,
        source_url=result.source_url,
        byte_count=result.byte_count,
        historical_payloads=result.historical_payloads,
        historical_errors=result.historical_errors,
        response_sha256=result.response_sha256,
        input_fingerprint=input_fingerprint,
        chunk_id=chunk_id,
    )
    terminal = result.terminal_error()
    if terminal and row["status"] == "ok":
        row["status"] = "partial" if row["filings"] else "failed"
        row["error"] = terminal
    if row["status"] not in TERMINAL_STATUSES:
        row["status"] = "failed"
        row["error"] = row["error"] or f"non-terminal status for CIK {cik_padded}"
    return row, result


def _run_chunk_rows(
    client: SubmissionsClient,
    ciks: tuple[str, ...],
    *,
    chunk_id: int,
    input_name: str,
    snapshot_id: str,
    input_fingerprint: str,
    workers: int,
    progress: Callable[[dict[str, Any]], None] | None,
) -> tuple[list[dict[str, Any]], int]:
    """Fetch every CIK in a chunk, returning rows in plan order."""
    rows: dict[str, dict[str, Any]] = {}
    historical_files = 0

    def emit(cik_padded: str, row: dict, result: CikFetchResult) -> None:
        nonlocal historical_files
        rows[cik_padded] = row
        historical_files += result.historical_files_fetched
        if progress is not None:
            progress(
                {
                    "type": "cik_normalized",
                    "cik": cik_padded,
                    "status": row["status"],
                    "historical_files": result.historical_files_fetched,
                }
            )

    with ThreadPoolExecutor(max_workers=resolve_workers(workers)) as pool:
        futures = [
            pool.submit(
                normalize_one_cik,
                client,
                cik_padded,
                input_name=input_name,
                snapshot_id=snapshot_id,
                input_fingerprint=input_fingerprint,
                chunk_id=chunk_id,
            )
            for cik_padded in ciks
        ]
        for processed, future in enumerate(futures, start=1):
            row, result = future.result()
            emit(cik_padded=ciks[processed - 1], row=row, result=result)
            if processed % RECLAIM_INTERVAL == 0:
                reclaim()

    reclaim()
    return [rows[cik] for cik in ciks], historical_files


def run_chunk(
    client: SubmissionsClient,
    plan: Plan,
    run_paths: RunPaths,
    chunk_id: int,
    *,
    snapshot_id: str,
    workers: int | None = None,
    force: bool = False,
    progress: Callable[[dict[str, Any]], None] | None = None,
) -> ChunkResult:
    """Execute one chunk and atomically write its checkpoint Parquet.

    A valid existing checkpoint short-circuits the run, so completed chunks
    are never refetched. The guarantee lives here rather than in each caller,
    because a refetch is exactly what makes a resume slow and a rerun
    non-idempotent.
    """
    ciks = plan.chunk_ciks(chunk_id)
    path = run_paths.chunk_file(chunk_id)
    if not force:
        existing = inspect_chunk(
            chunk_id,
            path,
            expected_ciks=ciks,
            expected_fingerprint=plan.input_fingerprint or None,
        )
        if existing is not None:
            return ChunkResult(
                chunk_id=chunk_id,
                path=str(path),
                row_count=existing.row_count,
                skipped_existing=True,
            )

    with StagedParquetWriter(
        path,
        schema=SUBMISSION_METADATA_SCHEMA,
        id_column="cik",
    ) as writer:
        existing_ciks = set() if force else writer.get_existing_ids()
        remaining_ciks = [c for c in ciks if c not in existing_ciks]

        rows: list[dict[str, Any]] = []
        if remaining_ciks:
            rows, _ = _run_chunk_rows(
                client,
                tuple(remaining_ciks),
                chunk_id=chunk_id,
                input_name=plan.input_name,
                snapshot_id=snapshot_id,
                input_fingerprint=plan.input_fingerprint,
                workers=workers,
                progress=progress,
            )
            table = build_submission_table(rows)
            writer.write_batch(table)

        total_rows = writer.commit(expected_count=len(ciks))

    statuses: dict[str, int] = {}
    historical_files = 0
    if total_rows > 0:
        table = read_parquet_table(path, columns=["status", "historical_files_total"])
        for status_val in table.column("status").to_pylist():
            statuses[status_val] = statuses.get(status_val, 0) + 1
        historical_files = sum(
            c for c in table.column("historical_files_total").to_pylist() if c
        )

    return ChunkResult(
        chunk_id=chunk_id,
        path=str(path),
        row_count=total_rows,
        statuses=statuses,
        historical_files=historical_files,
    )


def run_chunk_ids(
    client: SubmissionsClient,
    plan: Plan,
    run_paths: RunPaths,
    chunk_ids: list[int],
    *,
    snapshot_id: str,
    workers: int | None = None,
    completed: dict[int, Any] | None = None,
    progress: Callable[[dict[str, Any]], None] | None = None,
) -> list[ChunkResult]:
    """Run an explicit chunk list, skipping chunks already complete on disk.

    This is the single execution path for one host and for many. A local run
    passes every planned chunk; a worker running a copied bundle passes the
    chunk ids its assignment names, which is why assignment carries no
    scheduling logic of its own.
    """
    done = completed or {}
    results: list[ChunkResult] = []
    for chunk_id in chunk_ids:
        if chunk_id in done:
            results.append(
                ChunkResult(
                    chunk_id=chunk_id,
                    path=str(run_paths.chunk_file(chunk_id)),
                    row_count=0,
                    skipped_existing=True,
                )
            )
            continue
        results.append(
            run_chunk(
                client,
                plan,
                run_paths,
                chunk_id,
                snapshot_id=snapshot_id,
                workers=workers,
                progress=progress,
            )
        )
    return results
