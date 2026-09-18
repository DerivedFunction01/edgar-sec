"""End-to-end Phase 2.5 acquisition coordinator."""

from __future__ import annotations

from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from contextlib import suppress
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from defs.runtime.paths import resolve_paths

from .chunk_cache import find_completed_chunk_db, try_load_completed_chunk
from .chunk_persistence import ChunkResult
from .chunk_worker import process_chunk
from .fetcher import ArchiveFetcher, make_archive_fetcher
from .partition_merger import PartitionMergeResult, merge_partition
from .schemas import (
    DocumentLocator,
    FilingOccurrence,
    doc_id,
)
from .targets import (
    calculate_optimal_chunk_size,
    load_targets,
    partition_locators,
)


@dataclass(frozen=True, slots=True)
class _ChunkTask:
    index: int
    chunk_id: str
    worker_id: str
    chunk: list[DocumentLocator]
    chunk_occurrences: list[FilingOccurrence]
    chunk_path: Path


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
    selected = partition_locators(locators, partition_id, partition_count)

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
        cache_dir = None
        if (
            mode.strip().lower() == "production"
            and http_client is None
            and broker_socket is None
        ):
            from defs.sec_http.broker_cli import broker_cache_dir, ensure_broker

            broker_socket = ensure_broker().socket_path
            cache_dir = broker_cache_dir()
        fetcher = make_archive_fetcher(
            mode, fixture_paths, http_client, broker_socket, cache_dir=cache_dir
        )

    run_paths = resolve_paths("webpage_storage", run_id)
    run_paths.ensure_run_layout()

    # Plan-binding metadata and collision guard
    meta_file = run_paths.run_root / "run_metadata.json"
    if meta_file.exists():
        with suppress(Exception):
            from defs.storage import load_json

            existing_meta = load_json(meta_file)
            existing_plan = existing_meta.get("plan_id")
            cur_plan = plan.get("plan_id")
            if existing_plan and cur_plan and existing_plan != cur_plan:
                raise ValueError(
                    f"Run '{run_id}' was previously bound to plan '{existing_plan}', "
                    f"but current plan is '{cur_plan}'. Use a distinct --run-id "
                    f"or clear the run directory to avoid mixing chunk data."
                )

    from datetime import UTC, datetime

    from defs.storage import atomic_write_json

    run_meta = {
        "run_id": run_id,
        "phase": "webpage_storage",
        "mode": mode.strip().lower(),
        "plan_id": plan.get("plan_id"),
        "plan_dir": str(plan_dir),
        "scope": plan.get("scope"),
        "total_target_docs": len(selected),
        "total_plan_docs": len(locators),
        "partition_id": partition_id,
        "partition_count": partition_count,
        "chunk_size": effective_chunk_size,
        "workers": workers,
        "fixture_paths": (
            [str(p) for p in (fixture_paths or [])] if fixture_paths else None
        ),
        "started_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "status": "running",
    }
    atomic_write_json(meta_file, run_meta)

    chunk_count = (
        (len(selected) + effective_chunk_size - 1) // effective_chunk_size
        if selected
        else 0
    )
    chunk_results: list[ChunkResult | None] = [None] * chunk_count

    # Preflight completed chunks first so pending work can be materialized
    # lazily: only the in-flight window ever holds chunk slices and their
    # occurrence lists instead of the whole partition.
    pending_indices: list[int] = []
    for chunk_idx, start in enumerate(range(0, len(selected), effective_chunk_size)):
        chunk = selected[start : start + effective_chunk_size]
        chunk_id = f"chunk-{chunk_idx + 1:05d}"

        # Preflight check for already completed chunk
        existing_path = find_completed_chunk_db(run_paths, attempt_id, chunk_id)
        if existing_path is not None:
            cached = try_load_completed_chunk(chunk_id, existing_path, processor)
            if cached is not None:
                chunk_results[chunk_idx] = cached
                if progress is not None:
                    with suppress(Exception):
                        for _ in chunk:
                            progress({"type": "document_done", "status": "cached"})
                continue

        pending_indices.append(chunk_idx)

    locator_count = len(selected)
    # Release the coordinator's locator shell; occurrences stay reachable
    # through the by-doc-id map consumed lazily by the task generator.
    del locators

    def _pending_tasks():
        for chunk_idx in pending_indices:
            start = chunk_idx * effective_chunk_size
            chunk = selected[start : start + effective_chunk_size]
            chunk_id = f"chunk-{chunk_idx + 1:05d}"

            assigned_worker_num = (chunk_idx % workers) + 1
            chunk_worker_id = (
                worker_id if workers == 1 else f"worker-{assigned_worker_num:05d}"
            )
            chunk_path = run_paths.worker_chunk_db(
                chunk_worker_id, attempt_id, chunk_id
            )
            run_paths.ensure_worker_layout(chunk_worker_id, attempt_id)

            chunk_doc_ids = {
                doc_id(locator.accession, locator.document_path) for locator in chunk
            }
            chunk_occurrences = [
                occurrence
                for d_id in chunk_doc_ids
                for occurrence in occurrences_by_doc_id.get(d_id, ())
            ]

            yield _ChunkTask(
                index=chunk_idx,
                chunk_id=chunk_id,
                worker_id=chunk_worker_id,
                chunk=chunk,
                chunk_occurrences=chunk_occurrences,
                chunk_path=chunk_path,
            )

    try:
        if pending_indices:
            if workers <= 1:
                for task in _pending_tasks():
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
                    max_tasks_per_child=8,
                ) as pool:
                    max_in_flight = workers + 4
                    task_iter = _pending_tasks()
                    future_to_task: dict = {}

                    # Seed initial in-flight window
                    for _ in range(min(len(pending_indices), max_in_flight)):
                        initial_task = next(task_iter, None)
                        if initial_task is None:
                            break
                        fut = pool.submit(
                            process_chunk,
                            initial_task.chunk_id,
                            initial_task.worker_id,
                            initial_task.chunk,
                            initial_task.chunk_occurrences,
                            fetcher,
                            initial_task.chunk_path,
                            None,
                            processor,
                        )
                        future_to_task[fut] = initial_task

                    while future_to_task:
                        for future in as_completed(future_to_task):
                            task = future_to_task.pop(future)
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

                            # Feed next task into bounded window
                            next_task = next(task_iter, None)
                            if next_task is not None:
                                next_fut = pool.submit(
                                    process_chunk,
                                    next_task.chunk_id,
                                    next_task.worker_id,
                                    next_task.chunk,
                                    next_task.chunk_occurrences,
                                    fetcher,
                                    next_task.chunk_path,
                                    None,
                                    processor,
                                )
                                future_to_task[next_fut] = next_task
                            break
    finally:
        close = getattr(fetcher, "close", None)
        if close is not None:
            close()

    # Execution complete: release coordinator-side target state before merge.
    # Reassign rather than ``del`` — the lazy task generator closes over these
    # names, and it is fully consumed by the time execution finishes.
    occurrences_by_doc_id = None
    occurrences = None
    selected = None

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

    with suppress(Exception):
        run_meta["status"] = "completed"
        run_meta["completed_at"] = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        run_meta["blob_count"] = sum(r.blob_count for r in final_chunk_results)
        run_meta["failure_count"] = sum(len(r.failures) for r in final_chunk_results)
        atomic_write_json(meta_file, run_meta)

    return {
        "plan": plan,
        "partition_id": partition_id,
        "partition_count": partition_count,
        "locator_count": locator_count,
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


_partition_locators = partition_locators

__all__ = [
    "_partition_locators",
    "calculate_optimal_chunk_size",
    "load_targets",
    "partition_locators",
    "run_partition",
]
