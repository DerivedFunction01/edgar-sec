"""End-to-end Phase 2.5 acquisition coordinator."""

from __future__ import annotations

import json
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from contextlib import suppress
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from defs.runtime.paths import resolve_paths
from defs.sql import (
    Compare,
    ComparisonOp,
    Select,
    SqlDialect,
    Table,
    col,
    make_sql_executor,
    param,
)

from .chunk_worker import ChunkFailure, ChunkResult, process_chunk
from .fetcher import ArchiveFetcher, make_archive_fetcher
from .partition_merger import PartitionMergeResult, merge_partition
from .schemas import (
    ACQUISITION_FAILURE_COLUMNS,
    ACQUISITION_FAILURES_TABLE,
    COMMITTED_CHUNK_COLUMNS,
    COMMITTED_CHUNKS_TABLE,
    DOCUMENT_BLOBS_TABLE,
    FILING_OCCURRENCES_TABLE,
    CommittedChunk,
    DocumentLocator,
    FilingOccurrence,
    build_occurrence,
    doc_id,
)

REQUIRED_LOCATOR_COLUMNS = (
    "document_locator_key",
    "representative_accession",
    "document_path",
    "archive_url",
)
REQUIRED_TARGET_COLUMNS = (
    "occurrence_id",
    "document_locator_key",
    "source_cik",
    "accession",
    "form",
    "filing_date",
    "report_date",
    "document_path",
)


@dataclass(frozen=True, slots=True)
class _ChunkTask:
    index: int
    chunk_id: str
    worker_id: str
    chunk: list[DocumentLocator]
    chunk_occurrences: list[FilingOccurrence]
    chunk_path: Path


def _find_completed_chunk_db(run_paths, attempt_id: str, chunk_id: str) -> Path | None:
    matches = sorted(run_paths.workers_root.glob(f"*/{attempt_id}/{chunk_id}.db"))
    for path in matches:
        if path.is_file():
            return path
    return None


def _try_load_completed_chunk(chunk_id: str, chunk_path: Path) -> ChunkResult | None:
    if not chunk_path.is_file():
        return None
    try:
        executor = make_sql_executor(chunk_path, dialect=SqlDialect.SQLITE)
        try:
            audit_row = executor.query_one(
                executor.compiler.compile(
                    Select(
                        source=Table(COMMITTED_CHUNKS_TABLE),
                        projection=tuple(col(c) for c in COMMITTED_CHUNK_COLUMNS),
                        where=Compare(
                            col("chunk_id"), ComparisonOp.EQ, param(chunk_id)
                        ),
                    )
                )
            )
            if audit_row is None:
                return None
            audit = CommittedChunk.from_row(audit_row)
            blobs = executor.query(
                executor.compiler.compile(
                    Select(
                        source=Table(DOCUMENT_BLOBS_TABLE),
                        projection=(col("doc_id"),),
                    )
                )
            )
            occurrences = executor.query(
                executor.compiler.compile(
                    Select(
                        source=Table(FILING_OCCURRENCES_TABLE),
                        projection=(col("occurrence_id"),),
                    )
                )
            )
            failure_rows = executor.query(
                executor.compiler.compile(
                    Select(
                        source=Table(ACQUISITION_FAILURES_TABLE),
                        projection=tuple(col(c) for c in ACQUISITION_FAILURE_COLUMNS),
                    )
                )
            )
            failures = tuple(
                ChunkFailure(
                    locator=DocumentLocator(
                        locator_key=str(row["doc_id"]),
                        accession=str(row["accession"]),
                        document_path=str(row["document_path"]),
                        archive_url="",
                    ),
                    status=str(row["status"]),
                    error=str(row["error_message"] or row["status"]),
                )
                for row in failure_rows
            )
            return ChunkResult(
                chunk_id=chunk_id,
                worker_id=audit.worker_id,
                path=chunk_path,
                locator_count=len(blobs) + len(failure_rows),
                fetched_count=len(blobs),
                occurrence_count=len(occurrences),
                blob_count=len(blobs),
                failures=failures,
                audit=audit,
            )
        finally:
            executor.close()
    except Exception:  # noqa: BLE001 - corrupted or incomplete chunk dbs are reprocessed
        return None


def _read_parquet_rows(
    path: str | Path, columns: tuple[str, ...], view: str
) -> list[dict[str, Any]]:
    executor = make_sql_executor(
        dialect=SqlDialect.DUCKDB,
        dataset_views={view: str(path)},
    )
    try:
        query = Select(
            source=Table(view),
            projection=tuple(col(column) for column in columns),
        )
        return executor.query(executor.compiler.compile(query))
    finally:
        executor.close()


def _validate_bundle(plan_dir: Path) -> tuple[Path, Path, dict[str, Any]]:
    manifest = plan_dir / "plan.json"
    locator_path = plan_dir / "locator_groups.parquet"
    if not manifest.is_file():
        raise FileNotFoundError(f"Phase 02 plan manifest not found: {manifest}")
    if not locator_path.is_file():
        raise FileNotFoundError(f"Phase 02 locator groups not found: {locator_path}")
    with manifest.open("r", encoding="utf-8") as stream:
        plan = json.load(stream)
    if not isinstance(plan, dict):
        raise ValueError("Phase 02 plan.json must contain an object")
    target_paths = sorted((plan_dir / "targets").glob("form=*/data.parquet"))
    if not target_paths:
        raise FileNotFoundError(
            f"Phase 02 target parquet files not found under {plan_dir / 'targets'}"
        )
    return locator_path, target_paths[0], plan


def load_targets(
    plan_dir: str | Path,
) -> tuple[list[DocumentLocator], list[FilingOccurrence], dict[str, Any]]:
    """Read and validate the published Phase 02 plan bundle."""
    root = Path(plan_dir)
    locator_path, _first_target_path, plan = _validate_bundle(root)
    locator_rows = _read_parquet_rows(
        locator_path, REQUIRED_LOCATOR_COLUMNS, "locator_groups"
    )
    target_paths = sorted((root / "targets").glob("form=*/data.parquet"))
    target_rows: list[dict[str, Any]] = []
    for target_path in target_paths:
        target_rows.extend(
            _read_parquet_rows(target_path, REQUIRED_TARGET_COLUMNS, "target_rows")
        )
    if not locator_rows:
        return [], [], plan

    locators = [
        DocumentLocator(
            locator_key=str(row["document_locator_key"]),
            accession=str(row["representative_accession"]),
            document_path=str(row["document_path"]),
            archive_url=str(row["archive_url"]),
            form=str(row.get("form", "")),
        )
        for row in locator_rows
    ]
    locator_by_key = {locator.locator_key: locator for locator in locators}
    occurrences: list[FilingOccurrence] = []
    for row in target_rows:
        key = str(row["document_locator_key"])
        locator = locator_by_key.get(key)
        if locator is None:
            raise ValueError(f"target references unknown document locator: {key}")
        occurrence = build_occurrence(
            source_cik=str(row["source_cik"]),
            accession=str(row["accession"]),
            document_path=str(row["document_path"]),
            form=str(row["form"]),
            filing_date=str(row["filing_date"]),
            report_date=(
                None if row.get("report_date") is None else str(row["report_date"])
            ),
        )
        if occurrence.document_path != locator.document_path:
            raise ValueError(
                f"target document path disagrees with locator group: {key}"
            )
        occurrences.append(occurrence)
    return locators, occurrences, plan


def _partition_locators(
    locators: list[DocumentLocator], partition_id: int, partition_count: int
) -> list[DocumentLocator]:
    if partition_count < 1 or partition_id < 1 or partition_id > partition_count:
        raise ValueError("partition_id must be in the range 1..partition_count")
    ordered = sorted(locators, key=lambda locator: locator.locator_key)
    return [
        locator
        for index, locator in enumerate(ordered)
        if index % partition_count == partition_id - 1
    ]


def calculate_optimal_chunk_size(locator_count: int, workers: int = 1) -> int:
    """Calculate an optimal chunk size balancing concurrency and SQLite file overhead."""
    if locator_count <= 0:
        return 100
    target_chunks = max(1, workers * 4)
    computed = (locator_count + target_chunks - 1) // target_chunks
    return max(100, min(2500, computed))


def run_partition(
    plan_dir: str | Path,
    output_dir: str | Path,
    *,
    mode: str = "fixture",
    fixture_paths: list[str | Path] | None = None,
    http_client=None,
    run_id: str = "local",
    partition_id: int = 1,
    partition_count: int = 1,
    chunk_size: int | None = None,
    workers: int = 1,
    worker_id: str = "worker-00001",
    attempt_id: str = "attempt-00001",
    fetcher: ArchiveFetcher | None = None,
    broker_socket: str | Path | None = None,
    progress=None,
    processor=None,
) -> dict[str, Any]:
    """Acquire one deterministic partition and merge its worker chunks.

    When ``broker_socket`` is supplied in live mode, workers route archive
    fetches through the managed SEC broker instead of constructing
    independent SEC clients, so all live requests share one aggregate rate
    limiter.
    """
    if workers < 1:
        raise ValueError("workers must be positive")
    locators, occurrences, plan = load_targets(plan_dir)
    selected = _partition_locators(locators, partition_id, partition_count)

    effective_chunk_size = (
        chunk_size
        if (chunk_size is not None and chunk_size > 0)
        else calculate_optimal_chunk_size(len(selected), workers)
    )

    occurrences_by_doc_id: dict[str, list[FilingOccurrence]] = defaultdict(list)
    for occurrence in occurrences:
        occurrences_by_doc_id[occurrence.doc_id].append(occurrence)

    if fetcher is None:
        if mode.strip().lower() == "fixture" and not fixture_paths:
            raise ValueError("fixture mode requires fixture_paths")
        if (
            mode.strip().lower() == "production"
            and http_client is None
            and broker_socket is None
        ):
            from defs.sec_http.broker_cli import ensure_broker

            broker_socket = ensure_broker().socket_path
        fetcher = make_archive_fetcher(mode, fixture_paths, http_client, broker_socket)

    run_paths = resolve_paths("webpage_storage", run_id)
    run_paths.ensure_run_layout()

    tasks: list[_ChunkTask] = []
    chunk_count = (
        (len(selected) + effective_chunk_size - 1) // effective_chunk_size
        if selected
        else 0
    )
    chunk_results: list[ChunkResult | None] = [None] * chunk_count

    for chunk_idx, start in enumerate(range(0, len(selected), effective_chunk_size)):
        chunk = selected[start : start + effective_chunk_size]
        chunk_id = f"chunk-{chunk_idx + 1:05d}"

        # Preflight check for already completed chunk
        existing_path = _find_completed_chunk_db(run_paths, attempt_id, chunk_id)
        if existing_path is not None:
            cached = _try_load_completed_chunk(chunk_id, existing_path)
            if cached is not None:
                chunk_results[chunk_idx] = cached
                if progress is not None:
                    with suppress(Exception):
                        for _ in chunk:
                            progress({"type": "document_done", "status": "cached"})
                continue

        assigned_worker_num = (chunk_idx % workers) + 1
        chunk_worker_id = (
            worker_id if workers == 1 else f"worker-{assigned_worker_num:05d}"
        )
        chunk_path = run_paths.worker_chunk_db(chunk_worker_id, attempt_id, chunk_id)
        run_paths.ensure_worker_layout(chunk_worker_id, attempt_id)

        chunk_doc_ids = {
            doc_id(locator.accession, locator.document_path) for locator in chunk
        }
        chunk_occurrences = [
            occurrence
            for d_id in chunk_doc_ids
            for occurrence in occurrences_by_doc_id.get(d_id, ())
        ]

        tasks.append(
            _ChunkTask(
                index=chunk_idx,
                chunk_id=chunk_id,
                worker_id=chunk_worker_id,
                chunk=chunk,
                chunk_occurrences=chunk_occurrences,
                chunk_path=chunk_path,
            )
        )

    try:
        if tasks:
            if workers <= 1:
                for task in tasks:
                    chunk_results[task.index] = process_chunk(
                        task.chunk_id,
                        task.worker_id,
                        task.chunk,
                        task.chunk_occurrences,
                        fetcher,
                        task.chunk_path,
                        progress=progress,
                        processor=processor,
                    )
            else:
                import multiprocessing

                with ProcessPoolExecutor(
                    max_workers=workers,
                    mp_context=multiprocessing.get_context("spawn"),
                ) as pool:
                    future_to_task = {
                        pool.submit(
                            process_chunk,
                            task.chunk_id,
                            task.worker_id,
                            task.chunk,
                            task.chunk_occurrences,
                            fetcher,
                            task.chunk_path,
                            None,
                            processor,
                        ): task
                        for task in tasks
                    }
                    for future in as_completed(future_to_task):
                        task = future_to_task[future]
                        chunk_result = future.result()
                        chunk_results[task.index] = chunk_result
                        if progress is not None:
                            # Replay document completions after the isolated chunk returns.
                            for failure in chunk_result.failures:
                                progress(
                                    {
                                        "type": "document_done",
                                        "status": failure.status,
                                        "doc_id": doc_id(
                                            failure.locator.accession,
                                            failure.locator.document_path,
                                        ),
                                        "error": failure.error,
                                    }
                                )
                            for _ in range(chunk_result.blob_count):
                                progress(
                                    {
                                        "type": "document_done",
                                        "status": "ok",
                                        "chunk_id": task.chunk_id,
                                    }
                                )
                            progress(
                                {
                                    "type": "chunk_done",
                                    "chunk_id": task.chunk_id,
                                    "status": (
                                        "completed"
                                        if chunk_result.succeeded
                                        else "failed"
                                    ),
                                    "fetched_count": chunk_result.fetched_count,
                                }
                            )
    finally:
        close = getattr(fetcher, "close", None)
        if close is not None:
            close()

    final_chunk_results: list[ChunkResult] = [
        result for result in chunk_results if result is not None
    ]

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    partition_name = (
        resolve_paths()
        .dataset_manifests(
            "webpage_storage", "filing_documents", f"partition-{partition_id:05d}"
        )
        .name
        + ".sqlite"
    )
    partition_path = output / partition_name
    merge_result: PartitionMergeResult = merge_partition(
        partition_path, [result.path for result in final_chunk_results]
    )
    return {
        "plan": plan,
        "partition_id": partition_id,
        "partition_count": partition_count,
        "locator_count": len(selected),
        "chunk_size": effective_chunk_size,
        "occurrence_count": sum(
            result.occurrence_count for result in final_chunk_results
        ),
        "failures": [
            asdict(failure)
            for result in final_chunk_results
            for failure in result.failures
        ],
        "chunks": [
            {**asdict(result), "path": str(result.path)}
            for result in final_chunk_results
        ],
        "merge": merge_result.to_dict(),
        "partition_db": str(partition_path),
    }


__all__ = ["calculate_optimal_chunk_size", "load_targets", "run_partition"]
