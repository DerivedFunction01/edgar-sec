"""Catalog-specific checkpoint replay without changing generic work orders."""

from __future__ import annotations

import os
from collections import Counter
from concurrent.futures import FIRST_COMPLETED, Future, ProcessPoolExecutor, wait
from pathlib import Path
from typing import Any

from edgar_sec.foundation.hashing import sha256_text
from edgar_sec.foundation.runtime.memory import reclaim
from edgar_sec.foundation.runtime.resources import RuntimeResourceProfile
from edgar_sec.infra.storage.parquet import read_parquet_table
from edgar_sec.pipelines.document_storage.processor import (
    DocumentProcessor,
    FilingProcessor,
)
from edgar_sec.pipelines.document_storage.execution import (
    ChunkResult,
    RECLAIM_INTERVAL,
    process_chunk,
    resolved_worker_count,
)
from edgar_sec.pipelines.document_storage.checkpoint import (
    is_chunk_complete,
    read_catalog_delegations,
)
from edgar_sec.pipelines.document_storage.summary import candidate_summary
from edgar_sec.pipelines.document_storage.work_order import ChunkInput, WorkOrder


def _completed_result(
    chunk: ChunkInput,
    chunks_dir: Path,
    processor_fingerprint: str,
    delegations: tuple,
) -> ChunkResult:
    path = chunks_dir / f"chunk-{chunk.chunk_id}.parquet"
    table = read_parquet_table(path, columns=["document_locator_key", "status"])
    statuses: dict[str, str] = {}
    for key, status in zip(
        table.column("document_locator_key").to_pylist(),
        table.column("status").to_pylist(),
        strict=False,
    ):
        statuses[str(key)] = str(status)
    counts = Counter(statuses.values())
    candidates = candidate_summary(chunk.locators, chunk.occurrences)
    return ChunkResult(
        chunk_id=chunk.chunk_id,
        worker_id="reused",
        output_path=path,
        document_count=len(chunk.locators),
        normalized_count=counts.get("ok", 0),
        failed_count=counts.get("failed", 0),
        missing_count=counts.get("missing", 0),
        occurrences=table.num_rows,
        processor_fingerprint=processor_fingerprint,
        payload_sha256=sha256_text(
            f"{chunk.chunk_id}:{counts.get('ok', 0)}:{counts.get('failed', 0)}:"
            f"{counts.get('missing', 0)}:{len(chunk.locators)}"
        ),
        candidate_eligible_count=candidates[0],
        bundle_candidate_count=candidates[1],
        candidate_date_unresolved_count=candidates[2],
        delegations=delegations,
        execution_state="reused",
    )


def _complete_delegations(
    chunk: ChunkInput,
    chunks_dir: Path,
    fingerprint: str,
) -> tuple | None:
    if not is_chunk_complete(
        chunks_dir, chunk.chunk_id, processor_fingerprint=fingerprint
    ):
        return None
    return read_catalog_delegations(
        chunks_dir / f"chunk-{chunk.chunk_id}.parquet", chunk.chunk_id, fingerprint
    )


def _run_task(task: dict[str, Any]) -> ChunkResult:
    return process_chunk(
        task["chunk_id"],
        task["worker_id"],
        task["locators"],
        task["occurrences"],
        fetcher=task["fetcher"],
        processor=task["processor"],
        chunks_dir=task["chunks_dir"],
        profile=task["profile"],
        catalog_checkpoint=True,
        force_recompute=task["force_recompute"],
    )


def process_catalog_chunks(
    work_order: WorkOrder,
    *,
    fetcher: Any,
    processor: DocumentProcessor | None,
    chunks_dir: Path,
    workers: int | None,
    profile: RuntimeResourceProfile | None,
) -> tuple[ChunkResult, ...]:
    """Replay valid catalog checkpoints and process only incomplete chunks."""
    effective_processor = processor if processor is not None else FilingProcessor()
    fingerprint = getattr(
        effective_processor, "processor_fingerprint", "custom:unspecified"
    )
    worker_count = resolved_worker_count(profile, workers)
    results: dict[str, ChunkResult] = {}
    order: list[str] = []
    source = iter(work_order.iter_chunks())

    def next_task() -> dict[str, Any] | None:
        for chunk in source:
            order.append(chunk.chunk_id)
            delegations = _complete_delegations(chunk, chunks_dir, fingerprint)
            if delegations is not None:
                results[chunk.chunk_id] = _completed_result(
                    chunk, chunks_dir, fingerprint, delegations
                )
                continue
            force = is_chunk_complete(
                chunks_dir, chunk.chunk_id, processor_fingerprint=fingerprint
            )
            return {
                "chunk_id": chunk.chunk_id,
                "worker_id": f"worker-{os.getpid()}",
                "locators": list(chunk.locators),
                "occurrences": list(chunk.occurrences),
                "fetcher": fetcher,
                "processor": effective_processor,
                "chunks_dir": chunks_dir,
                "profile": profile,
                "force_recompute": force,
            }
        return None

    if worker_count <= 1:
        while (task := next_task()) is not None:
            results[task["chunk_id"]] = _run_task(task)
            reclaim()
    else:
        with ProcessPoolExecutor(
            max_workers=worker_count,
            max_tasks_per_child=RECLAIM_INTERVAL,
        ) as pool:
            in_flight: dict[Future[ChunkResult], str] = {}
            while len(in_flight) < worker_count:
                task = next_task()
                if task is None:
                    break
                in_flight[pool.submit(_run_task, task)] = task["chunk_id"]
            while in_flight:
                done, _ = wait(in_flight, return_when=FIRST_COMPLETED)
                for future in done:
                    chunk_id = in_flight.pop(future)
                    results[chunk_id] = future.result()
                    reclaim()
                for _ in range(len(done)):
                    task = next_task()
                    if task is None:
                        break
                    in_flight[pool.submit(_run_task, task)] = task["chunk_id"]

    return tuple(results[chunk_id] for chunk_id in order)


__all__ = ["process_catalog_chunks"]
