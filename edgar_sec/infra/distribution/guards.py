"""Bundle manifest emission and assignment-affinity validation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from edgar_sec.foundation.hashing import is_sha256_hex_digest
from edgar_sec.infra.storage.atomic import atomic_write_json

from .partition import derive_assignment_id
from .protocol import WorkerAssignment, WorkerReceipt

BUNDLE_MANIFEST_NAME = "bundle.json"
BUNDLE_SCHEMA_VERSION = 2


def write_bundle_manifest(bundle_dir: Path, assignment: WorkerAssignment) -> Path:
    bundle_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = bundle_dir / BUNDLE_MANIFEST_NAME
    payload = {
        "schema_version": BUNDLE_SCHEMA_VERSION,
        "pipeline": assignment.pipeline,
        "work_id": assignment.work_id,
        "work_digest": assignment.work_digest,
        "worker_id": assignment.worker_id,
        "assignment_id": assignment.assignment_id,
        "chunk_count": len(assignment.chunk_ids),
        "chunk_ids": list(assignment.chunk_ids),
        "metadata": assignment.metadata,
    }
    atomic_write_json(manifest_path, payload)
    return manifest_path


def read_bundle_manifest(bundle_dir: Path) -> dict[str, Any]:
    manifest_path = bundle_dir / BUNDLE_MANIFEST_NAME
    if not manifest_path.is_file():
        raise ValueError(f"bundle carries no {BUNDLE_MANIFEST_NAME}: {bundle_dir}")
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"bundle manifest unreadable: {manifest_path}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"bundle manifest is malformed: {manifest_path}")

    version = data.get("schema_version")
    if version == BUNDLE_SCHEMA_VERSION:
        for key in ("pipeline", "work_id", "work_digest", "worker_id", "assignment_id"):
            if not isinstance(data.get(key), str) or not data[key]:
                raise ValueError(f"bundle manifest has invalid {key!r}")
        if not is_sha256_hex_digest(data["work_digest"]):
            raise ValueError("bundle manifest has invalid work_digest")
        chunk_ids = data.get("chunk_ids")
        if (
            not isinstance(chunk_ids, list)
            or any(type(value) is not int or value < 0 for value in chunk_ids)
            or len(set(chunk_ids)) != len(chunk_ids)
            or chunk_ids != sorted(chunk_ids)
            or data.get("chunk_count") != len(chunk_ids)
            or not isinstance(data.get("metadata", {}), dict)
        ):
            raise ValueError("bundle manifest has invalid chunk assignment")
        expected_id = derive_assignment_id(
            data["pipeline"],
            data["work_id"],
            data["work_digest"],
            data["worker_id"],
            chunk_ids,
        )
        if data["assignment_id"] != expected_id:
            raise ValueError("bundle assignment identity is invalid")
    else:
        raise ValueError(f"unsupported bundle schema version: {version!r}")
    return data


def assert_pipeline_affinity(manifest: dict[str, Any], expected_pipeline: str) -> None:
    actual = manifest.get("pipeline")
    if actual != expected_pipeline:
        raise ValueError(
            f"pipeline mismatch: bundle belongs to {actual!r}, but invoked under {expected_pipeline!r}"
        )


def assert_receipt_affinity(receipt: WorkerReceipt, manifest: dict[str, Any]) -> None:
    expected = {
        "pipeline": manifest.get("pipeline"),
        "work_id": manifest.get("work_id"),
        "worker_id": manifest.get("worker_id"),
    }
    actual = {
        "pipeline": receipt.pipeline,
        "work_id": receipt.work_id,
        "worker_id": receipt.worker_id,
    }
    if actual != expected:
        raise ValueError("receipt identity does not match its worker bundle")
    assert_work_digest(manifest.get("work_digest"), receipt.work_digest)
    if receipt.assignment_id != manifest.get("assignment_id"):
        raise ValueError("receipt assignment does not match its worker bundle")
    assigned = tuple(manifest.get("chunk_ids", ()))
    if len(set(receipt.completed_chunks)) != len(receipt.completed_chunks) or not set(
        receipt.completed_chunks
    ).issubset(assigned):
        raise ValueError("receipt contains chunks outside its worker assignment")


def assert_work_digest(expected: str, actual: str) -> None:
    if not isinstance(expected, str) or expected != actual:
        raise ValueError("work digest does not match the resolved work")
