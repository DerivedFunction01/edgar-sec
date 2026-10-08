"""Bundle manifest emission and pipeline-affinity validation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from edgar_sec.infra.storage.atomic import atomic_write_json

from .protocol import WorkerAssignment

BUNDLE_MANIFEST_NAME = "bundle.json"


def write_bundle_manifest(bundle_dir: Path, assignment: WorkerAssignment) -> Path:
    """Emit standardized bundle.json recording provenance and pipeline affinity."""
    bundle_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = bundle_dir / BUNDLE_MANIFEST_NAME
    payload = {
        "schema_version": 1,
        "pipeline": assignment.pipeline,
        "plan_id": assignment.plan_id,
        "worker_id": assignment.worker_id,
        "assignment_id": assignment.metadata.get("assignment_id", ""),
        "chunk_count": len(assignment.chunk_ids),
        "chunk_ids": list(assignment.chunk_ids),
        "metadata": assignment.metadata,
    }
    atomic_write_json(manifest_path, payload)
    return manifest_path


def read_bundle_manifest(bundle_dir: Path) -> dict[str, Any]:
    """Read and validate root bundle.json manifest."""
    manifest_path = bundle_dir / BUNDLE_MANIFEST_NAME
    if not manifest_path.is_file():
        raise ValueError(f"bundle carries no {BUNDLE_MANIFEST_NAME}: {bundle_dir}")
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"bundle manifest unreadable: {manifest_path}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"bundle manifest is malformed: {manifest_path}")
    return data


def assert_pipeline_affinity(manifest: dict[str, Any], expected_pipeline: str) -> None:
    """Assert bundle matches the invoking pipeline to prevent cross-contamination."""
    actual = manifest.get("pipeline")
    if actual != expected_pipeline:
        raise ValueError(
            f"pipeline mismatch: bundle belongs to {actual!r}, but invoked under {expected_pipeline!r}"
        )
