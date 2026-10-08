"""Deterministic chunk-to-worker partitioning."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from edgar_sec.foundation.hashing import sha256_bytes

from .protocol import WorkerAssignment


def derive_assignment_id(
    pipeline: str, plan_id: str, worker_id: str, chunk_ids: Sequence[int]
) -> str:
    """Content-derived identity for a worker chunk assignment."""
    ordered = sorted(set(chunk_ids))
    if not ordered:
        raise ValueError(f"assignment for worker {worker_id!r} covers no chunks")
    material = ":".join(
        (
            "assignment-v1",
            pipeline,
            plan_id,
            worker_id,
            ",".join(str(cid) for cid in ordered),
        )
    )
    return sha256_bytes(material.encode("utf-8"))[:16]


def divide_chunks(chunk_count: int, worker_count: int) -> dict[str, tuple[int, ...]]:
    """Split chunk ids round-robin across named workers."""
    if worker_count < 1:
        raise ValueError(f"worker_count must be >= 1, got {worker_count}")
    if chunk_count < 1:
        raise ValueError(f"chunk_count must be >= 1, got {chunk_count}")

    workers = [f"worker-{index:02d}" for index in range(worker_count)]
    return {
        worker: tuple(
            chunk_id
            for chunk_id in range(chunk_count)
            if chunk_id % worker_count == index
        )
        for index, worker in enumerate(workers)
    }


def build_assignment(
    pipeline: str,
    plan_id: str,
    worker_id: str,
    chunk_ids: Sequence[int],
    metadata: dict[str, Any] | None = None,
) -> WorkerAssignment:
    """Construct a validated immutable WorkerAssignment."""
    ordered = tuple(sorted(set(chunk_ids)))
    meta = dict(metadata or {})
    meta["assignment_id"] = derive_assignment_id(pipeline, plan_id, worker_id, ordered)
    return WorkerAssignment(
        pipeline=pipeline,
        plan_id=plan_id,
        worker_id=worker_id,
        chunk_ids=ordered,
        metadata=meta,
    )
