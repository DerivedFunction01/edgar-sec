"""Execution engine for Phase 2 filing catalog snapshot materialization."""

from __future__ import annotations

import hashlib
import importlib
import json
import logging
import os
import shutil
from collections.abc import Callable
from pathlib import Path

from defs.runtime import resolve_paths
from defs.runtime.artifacts import (
    get_current_snapshot_pointer,
    update_current_snapshot_pointer,
)
from defs.runtime.resources import derive_resources
from defs.storage import (
    FinalizedDataset,
    StorageError,
    canonical_json,
    force_reclaim_memory,
    load_json,
)

from ..config import DEFAULT_SOURCE_BATCH_SIZE
from ..paths import resolve_filing_paths
from ..schemas import (
    PROFILE_COLUMNS,
    PROFILE_SCHEMA_VERSION,
    SCHEMA_VERSION,
)
from .sql import (
    build_part_unnest_query,
    build_profile_query,
)

SOURCE = importlib.import_module("phases.01_metadata_extraction.core.schemas")

logger = logging.getLogger("filing_extraction.materialize")
FALLBACK_POLICY_VERSION = "1"


def _emit(progress: Callable[[dict], None] | None, event: dict) -> None:
    if progress is None:
        return
    try:
        progress(event)
    except Exception:
        logger.exception("materialize progress callback failed")


def _catalog_id(source_hash: str, config: dict) -> str:
    value = canonical_json([source_hash, SOURCE.SCHEMA_VERSION, SCHEMA_VERSION, config])
    return hashlib.sha256(value.encode()).hexdigest()[:24]


def _resolve_source(
    source_artifact: str | None,
    source_manifest: str | None,
) -> tuple[str, dict | None]:
    handoff = None
    if source_manifest:
        handoff = load_json(source_manifest, default=None)
        artifact_root = resolve_paths().artifacts_root
        if handoff and handoff.get("manifest_kind", "").endswith("_snapshot"):
            source_artifact = str(source_manifest)
        elif handoff and "artifact_path" in handoff:
            source_artifact = str(artifact_root / handoff["artifact_path"])
        else:
            source_artifact = str(source_manifest)
    elif source_artifact and str(source_artifact).endswith(".json"):
        handoff = load_json(source_artifact, default=None)

    if not source_artifact:
        configured_paths = resolve_paths("filing_extraction")
        artifact_root = configured_paths.project.artifacts_root.resolve()
        pointer = get_current_snapshot_pointer(
            artifact_root, phase="metadata", dataset="submission_metadata"
        )
        if pointer:
            source_artifact = str(artifact_root / pointer["manifest_path"])
            handoff = load_json(source_artifact, default=None)
        else:
            pub = configured_paths.project.published_dataset_path(
                "metadata", "submission_metadata", "parquet"
            )
            if pub.is_file():
                source_artifact = str(pub)
            else:
                raise ValueError("source_artifact or source_manifest is required")
    return str(source_artifact), handoff


def _compute_sha256(path: str) -> str:
    return FinalizedDataset(path).sha256


def materialize(
    source_artifact: str | None = None,
    output_root: str | None = None,
    *,
    source_manifest: str | None = None,
    progress: Callable[[dict], None] | None = None,
    source_batch_size: int | None = None,
    threads: int | None = None,
    memory_limit: str | None = None,
    temp_directory: str | None = None,
) -> dict:
    """Materialize Phase 2 filing catalog snapshot from Phase 1 metadata snapshot.

    Without ``output_root`` the catalog snapshot is staged under the transient
    scratch tree and published atomically into the durable
    ``manifests/filing_extraction/filing_catalog/snapshots/<snapshot_id>/``
    tree, advancing the ``filing_catalog`` current-snapshot pointer. An explicit
    ``output_root`` (tests, external tools) writes the snapshot directory in
    place and never touches the pointer.
    """
    source_batch_size = source_batch_size or DEFAULT_SOURCE_BATCH_SIZE
    if source_batch_size < 1:
        raise ValueError("source_batch_size must be >= 1")

    source_path_str, handoff = _resolve_source(source_artifact, source_manifest)
    source = Path(source_path_str).resolve()
    if any(part in {"chunks", "checkpoints", "workers"} for part in source.parts):
        raise StorageError(
            "Phase 2 requires a finalized artifact, not a chunk/checkpoint"
        )

    fp = resolve_filing_paths()
    artifacts_root = fp.artifacts_root.resolve()
    report = load_json(source.parent / "merge_report.json", default=None)
    resources = derive_resources(
        cli_overrides={"runtime.temp_directory": temp_directory}
        if temp_directory
        else None
    )

    with FinalizedDataset(
        source_path_str,
        artifacts_root=artifacts_root,
        threads=threads if threads is not None else resources.threads,
        memory_limit=memory_limit or resources.memory_limit,
        temp_directory=resources.temp_directory,
    ) as artifact:
        if artifact.columns != SOURCE.SUBMISSION_METADATA_SCHEMA.names:
            raise StorageError(
                "source artifact columns do not match submission_metadata schema"
            )
        source_hash = artifact.sha256
        _emit(
            progress,
            {
                "type": "merge_stage",
                "stage": "validate_source",
                "rows": report["row_count"]
                if report and isinstance(report.get("row_count"), int)
                else None,
            },
        )

        snapshot_id = (
            handoff.get("snapshot_id")
            if handoff and "snapshot_id" in handoff
            else _catalog_id(
                source_hash, {"target_fallback_policy": FALLBACK_POLICY_VERSION}
            )
        )
        catalog_id = snapshot_id
        durable = output_root is None
        if durable:
            final_dir = fp.catalog_snapshot_dir(snapshot_id)
            staging_dir = fp.catalog_dir(snapshot_id)
            if final_dir.exists():
                raise StorageError(
                    "immutable catalog snapshot already exists: "
                    f"{final_dir}; prune it or advance to a new upstream snapshot"
                )
        else:
            final_dir = Path(output_root).resolve() / snapshot_id
            staging_dir = final_dir

        # Stage into transient scratch; the durable snapshot directory only
        # appears through one atomic publish step after all parts validate.
        if staging_dir.exists():
            shutil.rmtree(staging_dir, ignore_errors=True)
        staging_dir.mkdir(parents=True, exist_ok=True)
        snapshot_dir = staging_dir

        # Stage 1: Company Profiles
        profile_path = snapshot_dir / "company_profiles.parquet"
        profile_query = build_profile_query(artifact.relation)
        profile_count = artifact.copy_query(profile_query, str(profile_path))
        _emit(
            progress,
            {
                "type": "merge_stage",
                "stage": "company_profiles",
                "rows": profile_count,
            },
        )
        force_reclaim_memory()

        # Stage 2: Shard-Aligned Unnest
        target_dir = snapshot_dir / "filing_targets"
        if target_dir.exists():
            shutil.rmtree(target_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        part_paths = artifact.resolved_part_paths
        parts_metadata: list[dict] = []
        form_counts: dict[str, int] = {}
        total_target_rows = 0

        target_part_paths: list[str] = []
        for part_index, part_path in enumerate(part_paths):
            # Upstream shards may all use the basename ``part-000.parquet``
            # inside distinct shard directories. The snapshot contract is
            # flat, so assign deterministic names by resolved-part order.
            part_name = f"part-{part_index:05d}.parquet"
            dest_part = target_dir / part_name
            unnest_query = build_part_unnest_query(part_path)
            row_count = artifact.copy_query(unnest_query, str(dest_part))
            total_target_rows += row_count
            artifact_sha = _compute_sha256(str(dest_part))
            target_part_paths.append(str(dest_part))
            parts_metadata.append(
                {
                    "path": f"filing_targets/{part_name}",
                    "row_count": row_count,
                    "artifact_sha256": artifact_sha,
                }
            )
            _emit(
                progress,
                {
                    "type": "merge_stage",
                    "stage": f"targets:{part_name}",
                    "rows": row_count,
                },
            )
            force_reclaim_memory()

        # Aggregate per-form counts from all target parts
        if target_part_paths:
            for part_path in target_part_paths:
                for form_name, cnt in artifact.run(
                    f"""
                    SELECT form, COUNT(*)
                    FROM read_parquet('{part_path}')
                    WHERE form IS NOT NULL
                    GROUP BY form
                    ORDER BY COUNT(*) DESC
                    """
                ):
                    form_counts[str(form_name)] = int(cnt)

        # Stage 3: Snapshot Manifest & Active Pointer
        # Recorded paths always describe the final snapshot location, never
        # the transient staging directory used to assemble it.
        try:
            rel_dir = final_dir.relative_to(artifacts_root)
        except ValueError:
            rel_dir = final_dir

        manifest = {
            "manifest_kind": "filing_catalog_snapshot",
            "producer_phase": "filing_extraction",
            "dataset": "filing_catalog",
            "snapshot_id": snapshot_id,
            "catalog_id": catalog_id,
            "source_artifact_sha256": source_hash,
            "upstream_snapshot_id": handoff.get("snapshot_id") if handoff else None,
            "schema_version": SCHEMA_VERSION,
            "target_rows": total_target_rows,
            "company_profiles_rows": profile_count,
            "form_count": len(form_counts),
            "form_counts": form_counts,
            "parts": parts_metadata,
            "snapshot_path": str(rel_dir / "snapshot.manifest.json"),
            "company_profiles_path": str(rel_dir / "company_profiles.parquet"),
            "filing_targets_dir": str(rel_dir / "filing_targets"),
            "source_batch_size": source_batch_size,
        }
        manifest_path = snapshot_dir / "snapshot.manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        if durable:
            final_dir.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staging_dir, final_dir)
            update_current_snapshot_pointer(
                snapshot_id=snapshot_id,
                manifest_path=final_dir / "snapshot.manifest.json",
                phase="filing_extraction",
                dataset="filing_catalog",
                artifacts_root=artifacts_root,
            )
        _emit(
            progress,
            {
                "type": "merge_stage",
                "stage": "publish_manifest",
                "rows": manifest["target_rows"],
            },
        )
        return manifest


__all__ = [
    "FALLBACK_POLICY_VERSION",
    "PROFILE_COLUMNS",
    "PROFILE_SCHEMA_VERSION",
    "SCHEMA_VERSION",
    "materialize",
]
