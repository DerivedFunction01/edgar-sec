"""Portable finalized-partition handoff metadata."""

from __future__ import annotations

from pathlib import Path

from defs.storage import atomic_write_json, file_sha256, load_json

from .schemas import SCHEMA_VERSION

HANDOFF_SUFFIX = ".manifest.json"


def handoff_path(partition_db: str | Path) -> Path:
    path = Path(partition_db)
    return path.with_name(path.name + HANDOFF_SUFFIX)


def write_handoff(
    partition_db: str | Path,
    *,
    plan_id: str | None,
    run_id: str,
    partition_id: int,
    partition_count: int,
    base_snapshot_id: str | None = None,
    merge_result=None,
) -> dict:
    path = Path(partition_db).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"finalized partition database not found: {path}")
    result = {
        "manifest_kind": "webpage_storage_partition_handoff",
        "manifest_schema_version": "1.0.0",
        "phase": "webpage_storage",
        "dataset": "normalized_documents",
        "plan_id": plan_id,
        "run_id": run_id,
        "partition_id": int(partition_id),
        "partition_count": int(partition_count),
        "schema_version": str(SCHEMA_VERSION),
        "partition_db_path": path.name,
        "artifact_sha256": file_sha256(path),
        "base_snapshot_id": base_snapshot_id,
    }
    if merge_result is not None:
        result["merge"] = merge_result.to_dict()
    atomic_write_json(handoff_path(path), result, indent=2, sort_keys=True)
    return result


def validate_handoff(partition_db: str | Path) -> dict:
    path = Path(partition_db).resolve()
    manifest_file = handoff_path(path)
    if not path.is_file():
        raise FileNotFoundError(f"finalized partition database not found: {path}")
    if not manifest_file.is_file():
        raise FileNotFoundError(
            f"partition handoff manifest not found: {manifest_file}"
        )
    manifest = load_json(manifest_file)
    if manifest.get("manifest_kind") != "webpage_storage_partition_handoff":
        raise ValueError(f"invalid partition handoff manifest: {manifest_file}")
    if str(manifest.get("artifact_sha256")) != file_sha256(path):
        raise ValueError(f"partition handoff hash mismatch: {path}")
    if Path(str(manifest.get("partition_db_path"))).name != path.name:
        raise ValueError(f"partition handoff path mismatch: {manifest_file}")
    return manifest


def validate_handoffs(partition_dbs: list[str | Path]) -> list[dict]:
    """Validate a complete, non-overlapping finalized partition handoff."""
    manifests = [validate_handoff(path) for path in partition_dbs]
    plan_ids = {item.get("plan_id") for item in manifests if item.get("plan_id")}
    counts = {int(item["partition_count"]) for item in manifests}
    partition_ids = [int(item["partition_id"]) for item in manifests]
    if len(plan_ids) > 1:
        raise ValueError("partition handoffs reference different plans")
    if len(counts) != 1:
        raise ValueError("partition handoffs reference different partition counts")
    expected = set(range(1, next(iter(counts)) + 1))
    actual = set(partition_ids)
    if actual != expected:
        raise ValueError(
            f"partition handoff coverage mismatch: expected {sorted(expected)}, "
            f"got {sorted(actual)}"
        )
    if len(partition_ids) != len(actual):
        raise ValueError("duplicate partition IDs in handoff")
    return manifests


__all__ = [
    "HANDOFF_SUFFIX",
    "handoff_path",
    "validate_handoff",
    "validate_handoffs",
    "write_handoff",
]
