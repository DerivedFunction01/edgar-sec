"""Deterministic chunk and partition planning.

Planning performs no network access and no I/O beyond writing the plan itself.
The plan identifier is derived from the plan-defining inputs rather than a
timestamp, so replanning an unchanged input is idempotent while changing the
chunking produces a distinct plan.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from edgar_sec.domain.submissions.schemas import SCHEMA_VERSION
from edgar_sec.foundation.hashing import sha256_bytes
from edgar_sec.foundation.runtime.settings.runtime import (
    DEFAULT_CHUNK_SIZE,
    DEFAULT_PARTITION_COUNT,
)
from edgar_sec.infra.storage.atomic import atomic_write_json

from .manifest import InputManifest
from .paths import RunPaths

PLAN_FORMAT_VERSION = "1.0.0"

__all__ = ["build_plan", "derive_plan_id", "load_plan", "utc_now_iso", "write_plan"]


def utc_now_iso() -> str:
    """Current UTC time in second-resolution ISO 8601."""
    from datetime import UTC, datetime

    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def derive_plan_id(
    input_fingerprint: str, chunk_size: int, partition_count: int
) -> str:
    """Derive a stable plan identifier from the plan-defining inputs."""
    material = f"{input_fingerprint}:{chunk_size}:{partition_count}"
    return sha256_bytes(material.encode("utf-8"))[:16]


def _partition_for(chunk_index: int, partition_count: int) -> int:
    return chunk_index % partition_count


def _check_plan_version(plan: dict, key: str, expected: str, path: Path) -> None:
    """Reject a plan whose recorded version the current code no longer honours."""
    recorded = plan.get(key)
    if recorded != expected:
        raise ValueError(
            f"incompatible plan at {path}: {key} is {recorded!r}, this build "
            f"requires {expected!r}; regenerate the plan"
        )


def build_plan(
    manifest: InputManifest,
    *,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    partition_count: int = DEFAULT_PARTITION_COUNT,
    created_at: str | None = None,
) -> dict[str, Any]:
    """Build the immutable plan document for a manifest."""
    if chunk_size < 1:
        raise ValueError(f"chunk_size must be >= 1, got {chunk_size}")
    if partition_count < 1:
        raise ValueError(f"partition_count must be >= 1, got {partition_count}")

    ciks = list(manifest.ciks)
    chunks: list[dict[str, Any]] = [
        {
            "chunk_id": index,
            "offset": start,
            "cik_padded": ciks[start : start + chunk_size],
        }
        for index, start in enumerate(range(0, len(ciks), chunk_size))
    ]

    partitions: list[dict[str, Any]] = []
    for partition_id in range(partition_count):
        member_ids = [
            chunk["chunk_id"]
            for chunk in chunks
            if _partition_for(chunk["chunk_id"], partition_count) == partition_id
        ]
        if not member_ids:
            continue
        partitions.append(
            {
                "partition_id": partition_id,
                "chunk_ids": member_ids,
                "cik_padded": [
                    cik
                    for chunk in chunks
                    if chunk["chunk_id"] in member_ids
                    for cik in chunk["cik_padded"]
                ],
            }
        )

    assigned = [
        chunk_id
        for partition in partitions
        for chunk_id in partition["chunk_ids"]  # type: ignore[index]
    ]
    planned = [chunk["chunk_id"] for chunk in chunks]
    if sorted(assigned) != sorted(planned):
        raise ValueError(
            "partition assignment does not cover every planned chunk exactly once: "
            f"planned {planned}, assigned {assigned}"
        )

    plan_id = derive_plan_id(manifest.input_fingerprint, chunk_size, partition_count)
    return {
        "plan_id": plan_id,
        "plan_format_version": PLAN_FORMAT_VERSION,
        "schema_version": SCHEMA_VERSION,
        "created_at": created_at or utc_now_iso(),
        "input_name": manifest.input_name,
        "input_fingerprint": manifest.input_fingerprint,
        "chunk_size": chunk_size,
        "partition_count": partition_count,
        "row_count": len(ciks),
        "cik_padded": ciks,
        "chunks": chunks,
        "partitions": partitions,
        "skipped_rows": list(manifest.skipped),
        "duplicate_rows": manifest.duplicate_count,
    }


def write_plan(plan: dict[str, Any], run_paths: RunPaths) -> None:
    """Persist a plan atomically to its plan directory."""
    atomic_write_json(run_paths.plan_file, plan, canonical=False, indent=2)


def load_plan(run_paths: RunPaths) -> dict[str, Any]:
    """Load and validate a previously written plan.

    A plan written for different plan-defining inputs is rejected rather than
    silently reused, so a stale plan can never produce a mislabeled snapshot. A
    plan written under a different schema or plan format is rejected too: the
    recorded versions are part of the plan's identity, and replaying a plan the
    current code no longer honours would silently mislabel the snapshot.
    """
    import json

    path = run_paths.plan_file
    if not path.is_file():
        raise FileNotFoundError(f"missing plan: {path}")
    plan = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(plan, dict):
        raise ValueError(f"plan is not a JSON object: {path}")

    _check_plan_version(plan, "plan_format_version", PLAN_FORMAT_VERSION, path)
    _check_plan_version(plan, "schema_version", SCHEMA_VERSION, path)

    expected = derive_plan_id(
        str(plan.get("input_fingerprint", "")),
        int(plan.get("chunk_size", 0)),
        int(plan.get("partition_count", 0)),
    )
    if plan.get("plan_id") != expected:
        raise ValueError(
            f"stale plan at {path}: plan_id {plan.get('plan_id')!r} does not match "
            f"its recorded inputs (expected {expected!r}); regenerate the plan"
        )

    ciks = plan.get("cik_padded")
    chunk_ciks = [
        cik for chunk in plan.get("chunks", []) for cik in chunk.get("cik_padded", [])
    ]
    if chunk_ciks != ciks:
        raise ValueError(
            f"corrupt plan at {path}: chunk boundaries do not reconstruct the CIK list"
        )
    if int(plan.get("row_count", -1)) != len(ciks or []):
        raise ValueError(
            f"corrupt plan at {path}: row_count {plan.get('row_count')!r} "
            f"does not match {len(ciks or [])} CIKs"
        )
    return plan


def plan_chunk_ids(plan: dict[str, Any], partition_id: int | None = None) -> list[int]:
    """List planned chunk ids, optionally restricted to one partition."""
    if partition_id is None:
        return [int(chunk["chunk_id"]) for chunk in plan.get("chunks", [])]
    for partition in plan.get("partitions", []):
        if int(partition["partition_id"]) == partition_id:
            return [int(chunk_id) for chunk_id in partition["chunk_ids"]]
    return []
