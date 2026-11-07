"""Resumable chunk execution.
Every requested CIK produces exactly one row, including failures, so completion is
determinable from the data rather than queue state. Fetches run on threads: the
HTTP client and its SQLite cache are thread-safe and the work is network-bound.
"""

from __future__ import annotations

import multiprocessing
import signal
from collections.abc import Callable, Iterator, Mapping, Sequence
from concurrent.futures import (
    FIRST_COMPLETED,
    ProcessPoolExecutor,
    ThreadPoolExecutor,
    wait,
)
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.compute as pc

from edgar_sec.domain.submissions.schemas import (
    SUBMISSION_METADATA_SCHEMA,
    TERMINAL_STATUSES,
)
from edgar_sec.engine.submissions.builder import (
    build_submission_table,
    normalize_submissions,
)
from edgar_sec.foundation.runtime.memory import reclaim
from edgar_sec.infra.storage.duckdb import arrow_reader, connect
from edgar_sec.infra.storage.parquet import (
    StagedParquetWriter,
    cast_table,
    read_parquet_table,
    write_parquet_table,
)

from .checkpoints import inspect_chunk
from .paths import RunPaths
from .planner import Plan, utc_now_iso, write_fingerprints
from .sec_client import (
    BulkSubmissionsArchive,
    BulkSubmissionsClient,
    CikFetchResult,
    SubmissionsClient,
)

RECLAIM_INTERVAL = 64

__all__ = [
    "CarryProvider",
    "CarryReport",
    "ChunkResult",
    "normalize_one_cik",
    "resolve_workers",
    "run_chunk",
    "run_chunk_ids",
    "stage_carried_rows",
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
    client: SubmissionsClient | BulkSubmissionsClient,
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


def _fingerprint_for(
    fingerprints: Mapping[str, str] | None, cik: str, fallback: str
) -> str:
    if fingerprints is None:
        return fallback
    return fingerprints.get(cik, fallback)


def _run_chunk_rows(
    client: SubmissionsClient | BulkSubmissionsClient,
    writer: StagedParquetWriter,
    ciks: tuple[str, ...],
    *,
    chunk_id: int,
    input_name: str,
    snapshot_id: str,
    input_fingerprint: str,
    workers: int,
    progress: Callable[[dict[str, Any]], None] | None,
    fingerprints: Mapping[str, str] | None = None,
) -> int:
    """Fetch every CIK, writing each normalized row to the stage at once."""
    historical_files = 0
    processed = 0

    with ThreadPoolExecutor(max_workers=resolve_workers(workers)) as pool:
        pending = {
            pool.submit(
                normalize_one_cik,
                client,
                cik_padded,
                input_name=input_name,
                snapshot_id=snapshot_id,
                input_fingerprint=_fingerprint_for(
                    fingerprints, cik_padded, input_fingerprint
                ),
                chunk_id=chunk_id,
            ): cik_padded
            for cik_padded in ciks
        }
        while pending:
            done, _ = wait(pending, return_when=FIRST_COMPLETED)
            # A batch can complete several futures at once and ``done`` is a
            # set, so write every successful row before re-raising: a raising
            # future must not discard work that already finished.
            failure: Exception | None = None
            for future in done:
                cik_padded = pending.pop(future)
                try:
                    row, result = future.result()
                except Exception as exc:
                    # A raising future must not discard rows that already finished.
                    if failure is None:
                        failure = exc
                    continue
                historical_files += result.historical_files_fetched
                writer.write_batch(build_submission_table([row]))
                processed += 1
                if progress is not None:
                    progress(
                        {
                            "type": "cik_normalized",
                            "cik": cik_padded,
                            "status": row["status"],
                            "historical_files": result.historical_files_fetched,
                        }
                    )
                del row, result
                if processed % RECLAIM_INTERVAL == 0:
                    reclaim()
            if failure is not None:
                raise failure

    reclaim()
    return historical_files


_BULK_CLIENT: BulkSubmissionsClient | None = None


def _init_bulk_client(zip_path: str, archive_sha256: str) -> None:
    """Pool initializer: open this child's own handle on the bulk archive."""
    global _BULK_CLIENT
    _BULK_CLIENT = BulkSubmissionsClient(
        BulkSubmissionsArchive(zip_path, archive_sha256=archive_sha256)
    )


def _normalize_bulk_cik(
    task: tuple[str, str, str, str, int],
) -> tuple[dict[str, Any], int]:
    """Normalize one CIK in a pool child from the bulk archive."""
    cik_padded, input_name, snapshot_id, input_fingerprint, chunk_id = task
    if _BULK_CLIENT is None:  # pragma: no cover - initializer always runs first
        raise RuntimeError("bulk pool child was not initialized")
    row, result = normalize_one_cik(
        _BULK_CLIENT,
        cik_padded,
        input_name=input_name,
        snapshot_id=snapshot_id,
        input_fingerprint=input_fingerprint,
        chunk_id=chunk_id,
    )
    return row, result.historical_files_fetched


def _run_chunk_rows_bulk(
    pool: ProcessPoolExecutor,
    writer: StagedParquetWriter,
    ciks: tuple[str, ...],
    *,
    chunk_id: int,
    input_name: str,
    snapshot_id: str,
    input_fingerprint: str,
    progress: Callable[[dict[str, Any]], None] | None,
    fingerprints: Mapping[str, str] | None = None,
) -> int:
    """Normalize bulk CIKs on the process pool, writing each row at once."""
    historical_files = 0
    processed = 0
    pending = {
        pool.submit(
            _normalize_bulk_cik,
            (
                cik_padded,
                input_name,
                snapshot_id,
                _fingerprint_for(fingerprints, cik_padded, input_fingerprint),
                chunk_id,
            ),
        ): cik_padded
        for cik_padded in ciks
    }
    while pending:
        done, _ = wait(pending, return_when=FIRST_COMPLETED)
        failure: Exception | None = None
        for future in done:
            cik_padded = pending.pop(future)
            try:
                row, fetched = future.result()
            except Exception as exc:
                if failure is None:
                    failure = exc
                continue
            historical_files += fetched
            writer.write_batch(build_submission_table([row]))
            processed += 1
            if progress is not None:
                progress(
                    {
                        "type": "cik_normalized",
                        "cik": cik_padded,
                        "status": row["status"],
                        "historical_files": fetched,
                    }
                )
            del row
            if processed % RECLAIM_INTERVAL == 0:
                reclaim()
        if failure is not None:
            raise failure
    reclaim()
    return historical_files


@dataclass(frozen=True, slots=True)
class CarryReport:
    """Outcome of staging prior rows whose member fingerprint still matches."""

    staging_dir: Path
    carried_rows: int
    carried_by_chunk: dict[int, int]


class CarryProvider:
    """Per-chunk read access to rows staged by :func:`stage_carried_rows`."""

    def __init__(self, staging_dir: Path) -> None:
        self._staging_dir = staging_dir

    def table_for(self, chunk_id: int) -> pa.Table | None:
        """Carried rows for one chunk, or ``None`` when none were staged.

        A CIK staged more than once keeps its last staged row, matching the
        order the staging pass encountered the prior parts in.
        """
        paths = sorted(self._staging_dir.glob(f"chunk_{chunk_id:04d}.*.parquet"))
        if not paths:
            return None
        tables = [read_parquet_table(path) for path in paths]
        table = tables[0] if len(tables) == 1 else pa.concat_tables(tables)
        last: dict[str, int] = {}
        for position, cik in enumerate(table.column("cik").to_pylist()):
            last[str(cik)] = position
        if len(last) != table.num_rows:
            table = table.take(pa.array(sorted(last.values()), type=pa.int64()))
        return table


CARRY_BUFFER_ROWS = 8192
CARRY_BUFFER_BYTES = 128 * 1024 * 1024
CARRY_BATCH_ROWS = 256

_CARRY_SQL = """
SELECT p.*, r.ordinal AS __carry_ordinal
FROM read_parquet(?) p
JOIN read_parquet(?) r ON r.cik_padded = p.cik
JOIN read_parquet(?) f
  ON f.cik_padded = p.cik AND f.fingerprint = p.input_fingerprint
"""

_SNAPSHOT_ID_INDEX = SUBMISSION_METADATA_SCHEMA.get_field_index("snapshot_id")
_FETCHED_AT_INDEX = SUBMISSION_METADATA_SCHEMA.get_field_index("fetched_at")


def stage_carried_rows(
    plan: Plan,
    run_paths: RunPaths,
    *,
    prior_part_paths: Sequence[Path],
    fingerprints: Mapping[str, str] | None = None,
    fingerprints_path: Path | None = None,
    snapshot_id: str,
) -> CarryReport:
    """Stage prior-snapshot rows whose fingerprint matches the current archive.

    Carriage is decided by a DuckDB join on (cik, fingerprint); carried
    rows stream in bounded Arrow batches, re-stamped only in identity.
    """
    staging_dir = run_paths.metadata.transient_dir(f"carry-{plan.plan_id}") / "chunks"
    staging_dir.mkdir(parents=True, exist_ok=True)
    if fingerprints_path is None:
        if fingerprints is None:
            raise ValueError("carry staging requires a fingerprint dataset")
        fingerprints_path = staging_dir.parent / "fingerprints.parquet"
        write_fingerprints(fingerprints, fingerprints_path)
    if not prior_part_paths:
        return CarryReport(staging_dir=staging_dir, carried_rows=0, carried_by_chunk={})
    roster_path = plan.roster.dataset
    if roster_path is None:
        raise ValueError("carry staging requires a roster dataset")
    stamp = utc_now_iso()
    buffers: dict[int, list[pa.Table]] = {}
    spills: dict[int, int] = {}
    carried_by_chunk: dict[int, int] = {}
    buffered_rows = 0
    buffered_bytes = 0

    def flush(chunk_id: int) -> None:
        tables = buffers.pop(chunk_id, [])
        if not tables:
            return
        table = tables[0] if len(tables) == 1 else pa.concat_tables(tables)
        spill = spills.get(chunk_id, 0)
        spills[chunk_id] = spill + 1
        write_parquet_table(
            table, staging_dir / f"chunk_{chunk_id:04d}.{spill}.parquet"
        )
        carried_by_chunk[chunk_id] = carried_by_chunk.get(chunk_id, 0) + table.num_rows

    con = connect()
    try:
        reader = arrow_reader(
            con,
            _CARRY_SQL,
            params=[
                [str(part) for part in prior_part_paths],
                str(roster_path),
                str(fingerprints_path),
            ],
            batch_size=CARRY_BATCH_ROWS,
        )
        for batch in reader:
            ordinals = batch.column("__carry_ordinal")
            table = cast_table(
                pa.Table.from_batches([batch]), SUBMISSION_METADATA_SCHEMA
            )
            table = table.set_column(
                _SNAPSHOT_ID_INDEX,
                "snapshot_id",
                pa.array([snapshot_id] * table.num_rows, type=pa.string()),
            )
            table = table.set_column(
                _FETCHED_AT_INDEX,
                "fetched_at",
                pa.array([stamp] * table.num_rows, type=pa.string()),
            )
            chunk_ids = pc.divide(ordinals, plan.chunk_size)
            for chunk_id in pc.unique(chunk_ids).to_pylist():
                part = table.filter(pc.equal(chunk_ids, int(chunk_id)))
                buffers.setdefault(int(chunk_id), []).append(part)
                buffered_rows += part.num_rows
                buffered_bytes += part.nbytes
            if (
                buffered_rows >= CARRY_BUFFER_ROWS
                or buffered_bytes >= CARRY_BUFFER_BYTES
            ):
                for open_chunk in sorted(buffers):
                    flush(open_chunk)
                buffered_rows = 0
                buffered_bytes = 0
                reclaim()
    finally:
        con.close()
    for open_chunk in sorted(buffers):
        flush(open_chunk)
    reclaim()
    return CarryReport(
        staging_dir=staging_dir,
        carried_rows=sum(carried_by_chunk.values()),
        carried_by_chunk=carried_by_chunk,
    )


def run_chunk(
    client: SubmissionsClient | BulkSubmissionsClient,
    plan: Plan,
    run_paths: RunPaths,
    chunk_id: int,
    *,
    snapshot_id: str,
    workers: int | None = None,
    force: bool = False,
    progress: Callable[[dict[str, Any]], None] | None = None,
    bulk_pool: ProcessPoolExecutor | None = None,
    fingerprints: Mapping[str, str] | None = None,
    carry_table: pa.Table | None = None,
) -> ChunkResult:
    """Execute one chunk and atomically write its checkpoint Parquet.
    A valid existing checkpoint short-circuits the run.
    """
    ciks = plan.chunk_ciks(chunk_id)
    path = run_paths.chunk_file(chunk_id)
    if not force:
        existing = inspect_chunk(
            chunk_id,
            path,
            expected_ciks=ciks,
            expected_fingerprint=plan.input_fingerprint or None,
            expected_fingerprints=fingerprints,
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
        preserve_on_error=True,
    ) as writer:
        existing_ciks = set() if force else writer.get_existing_ids()
        remaining_ciks = tuple(c for c in ciks if c not in existing_ciks)

        if remaining_ciks and carry_table is not None and carry_table.num_rows:
            positions = pc.index_in(
                carry_table.column("cik"),
                value_set=pa.array(remaining_ciks, type=pa.string()),
            )
            matched = [
                (int(position), row_index)
                for row_index, position in enumerate(positions.to_pylist())
                if position is not None
            ]
            if matched:
                matched.sort()
                carried = carry_table.take(
                    pa.array([row_index for _pos, row_index in matched])
                )
                writer.write_batch(carried)
                carried_ciks = {remaining_ciks[pos] for pos, _row in matched}
                if progress is not None:
                    for cik, status in zip(
                        carried.column("cik").to_pylist(),
                        carried.column("status").to_pylist(),
                        strict=True,
                    ):
                        progress(
                            {
                                "type": "cik_normalized",
                                "cik": str(cik),
                                "status": status,
                                "historical_files": 0,
                            }
                        )
                remaining_ciks = tuple(
                    cik for cik in remaining_ciks if cik not in carried_ciks
                )

        if remaining_ciks:
            if bulk_pool is not None:
                _run_chunk_rows_bulk(
                    bulk_pool,
                    writer,
                    remaining_ciks,
                    chunk_id=chunk_id,
                    input_name=plan.input_name,
                    snapshot_id=snapshot_id,
                    input_fingerprint=plan.input_fingerprint,
                    progress=progress,
                    fingerprints=fingerprints,
                )
            else:
                _run_chunk_rows(
                    client,
                    writer,
                    remaining_ciks,
                    chunk_id=chunk_id,
                    input_name=plan.input_name,
                    snapshot_id=snapshot_id,
                    input_fingerprint=plan.input_fingerprint,
                    workers=workers,
                    progress=progress,
                    fingerprints=fingerprints,
                )

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


def _raise_interrupt(signum: int, frame: Any) -> None:
    """Turn a termination signal into the same path as Ctrl-C."""
    raise KeyboardInterrupt


@contextmanager
def _graceful_sigterm() -> Iterator[None]:
    """Translate SIGTERM into KeyboardInterrupt for the duration of a run.

    Only the main thread may install a handler, and the previous one is always
    restored, so a nested run cannot leak the translation.
    """
    try:
        previous = signal.signal(signal.SIGTERM, _raise_interrupt)
    except ValueError:
        yield
        return
    try:
        yield
    finally:
        signal.signal(signal.SIGTERM, previous)


def run_chunk_ids(
    client: SubmissionsClient | BulkSubmissionsClient,
    plan: Plan,
    run_paths: RunPaths,
    chunk_ids: list[int],
    *,
    snapshot_id: str,
    workers: int | None = None,
    completed: dict[int, Any] | None = None,
    progress: Callable[[dict[str, Any]], None] | None = None,
    fingerprints: Mapping[str, str] | None = None,
    carry: CarryProvider | None = None,
) -> list[ChunkResult]:
    """Run an explicit chunk list, skipping chunks already complete on disk.
    The single execution path for one host and for many.
    """
    done = completed or {}
    results: list[ChunkResult] = []
    bulk_pool: ProcessPoolExecutor | None = None
    if isinstance(client, BulkSubmissionsClient) and any(
        chunk_id not in done for chunk_id in chunk_ids
    ):
        # Bulk normalize is pure-Python and GIL-bound, so it runs on a spawn
        # process pool created once per run and held warm across chunks; the
        # per-CIK fetch path keeps its thread pool, being network-bound.
        bulk_pool = ProcessPoolExecutor(
            max_workers=resolve_workers(workers),
            mp_context=multiprocessing.get_context("spawn"),
            initializer=_init_bulk_client,
            initargs=(
                str(client.archive.zip_path),
                client.archive.archive_sha256,
            ),
        )
    try:
        with _graceful_sigterm():
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
                        bulk_pool=bulk_pool,
                        fingerprints=fingerprints,
                        carry_table=carry.table_for(chunk_id) if carry else None,
                    )
                )
    finally:
        if bulk_pool is not None:
            bulk_pool.shutdown()
    return results
