"""Phase 1 fresh and augmentation plan construction."""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from pathlib import Path

from defs.storage import atomic_write_json, file_sha256

from .augmentation import (
    artifacts_root,
    base_ciks,
    write_worklist,
)
from .chunks import assign_chunks, assign_partitions, plan_hash, verify_chunk_assignment
from .config import RunOptions
from .input_manifest import input_fingerprint, read_input_manifest
from .registry import compare_sources
from .schemas import SCHEMA_VERSION
from .source_registry import load_source_snapshot

logger = logging.getLogger("metadata.planning")


def _utc_now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_plan(options: RunOptions) -> dict:
    """Build and publish a deterministic fresh or augmentation plan."""
    base_manifest = None
    source_manifest = None
    effective_input_fingerprint = None
    if options.augmentation:
        root = artifacts_root(options.base_metadata_manifest or options.artifacts_dir)
        source = load_source_snapshot(options.source_manifest, artifacts_root=root)
        source_manifest = source.manifest
        base_manifest, _base_artifact, base_ciks_set = base_ciks(
            options.base_metadata_manifest, root
        )
        registry = compare_sources(
            curated_input_path=options.input_path,
            source_manifest_path=options.source_manifest,
            artifacts_root=root,
        )
        effective_rows, effective_report = read_input_manifest(
            registry["effective_csv_path"], limit=options.limit
        )
        effective_input_fingerprint = effective_report["fingerprint"]
        rows = [row for row in effective_rows if row.cik_padded not in base_ciks_set]
        report = {
            **effective_report,
            "fingerprint": input_fingerprint(rows),
            "row_count": len(rows),
        }
        worklist_path, worklist_manifest = write_worklist(
            rows,
            options=options,
            source_snapshot_id=source_manifest["snapshot_id"],
            base_manifest=base_manifest,
            root=root,
        )
    else:
        rows, report = read_input_manifest(options.input_path, limit=options.limit)
        worklist_path = None
        worklist_manifest = None
    ciks = [row.cik_padded for row in rows]
    chunks = assign_chunks(ciks, options.chunk_size)
    partitions = assign_partitions(ciks, options.partition_count, options.chunk_size)
    verify_chunk_assignment(rows, chunks)
    root = artifacts_root(options.base_metadata_manifest or options.artifacts_dir)
    plan = {
        "schema_version": SCHEMA_VERSION,
        "created_at": _utc_now_iso(),
        "input_path": options.input_path,
        "input_fingerprint": report["fingerprint"],
        "row_count": len(rows),
        "chunk_size": options.chunk_size,
        "partition_count": options.partition_count,
        "partition_assignment": "round_robin_v1",
        "storage_format": options.storage_format,
        "augmentation": options.augmentation,
        "source_manifest": options.source_manifest,
        "base_metadata_manifest": options.base_metadata_manifest,
        "effective_input_fingerprint": effective_input_fingerprint,
        "worklist_path": (
            str(worklist_path.relative_to(root)) if worklist_path is not None else None
        ),
        "worklist_manifest_id": (
            worklist_manifest["artifact_id"] if worklist_manifest else None
        ),
        "worklist_sha256": file_sha256(worklist_path) if worklist_path else None,
        "malformed": report["malformed"],
        "duplicates": report["duplicates"],
        "cik_padded": ciks,
        "chunks": [chunk.to_dict() for chunk in chunks],
        "partitions": [partition.to_dict() for partition in partitions],
        "run_options": {
            "input_path": options.input_path,
            "artifacts_dir": options.artifacts_dir,
            "chunk_size": options.chunk_size,
            "partition_count": options.partition_count,
            "limit": options.limit,
            "storage_format": options.storage_format,
            "source_manifest": options.source_manifest,
            "base_metadata_manifest": options.base_metadata_manifest,
            "augmentation": options.augmentation,
        },
    }
    if options.augmentation:
        partition_root = (
            Path("manifests")
            / "metadata"
            / "submission_metadata"
            / "augmentations"
            / options.run_id
        )
        plan["partition_artifacts"] = {
            str(partition.partition_id): (
                partition_root
                / f"partition-{partition.partition_id:05d}"
                / "submission_metadata.parquet"
            ).as_posix()
            for partition in partitions
        }
    plan["plan_hash"] = plan_hash(plan)
    os.makedirs(options.artifacts_dir, exist_ok=True)
    plan_path = os.path.join(options.artifacts_dir, "plan.json")
    atomic_write_json(plan_path, plan, indent=2, sort_keys=True)
    partitions_dir = os.path.join(options.artifacts_dir, "partitions")
    for partition in partitions:
        partition_path = os.path.join(
            partitions_dir, f"partition-{partition.partition_id:05d}.json"
        )
        atomic_write_json(partition_path, partition.to_dict(), indent=2, sort_keys=True)
    logger.info(
        "plan: %d CIKs, %d chunks, %d malformed, %d duplicates -> %s",
        len(rows),
        len(chunks),
        len(report["malformed"]),
        len(report["duplicates"]),
        plan_path,
    )
    return plan


__all__ = ["build_plan"]
