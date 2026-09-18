"""Phase 1 augmentation worklists and immutable snapshot publication."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from defs.runtime.artifacts import (
    artifact_id,
    find_manifests,
    make_manifest,
    make_snapshot_manifest,
    manifest_relative_path,
    publish_manifest,
    publish_snapshot_manifest,
    resolve_manifest,
)
from defs.runtime.paths import merge_report_path_in
from defs.runtime.resources import derive_resources
from defs.storage import (
    atomic_write_json,
    file_sha256,
    load_json,
    pa,
    write_table_atomic,
)
from defs.storage.finalized import FinalizedArtifact

from .config import RunOptions
from .input_manifest import TargetRow, read_input_manifest
from .merge import MergeError, MergeReport
from .schemas import SCHEMA_VERSION
from .source_registry import WORKLIST_SCHEMA, load_worklist


def artifacts_root(path: str | Path) -> Path:
    value = Path(path).resolve()
    for marker in ("transient", "manifests", "metadata"):
        if marker in value.parts:
            return Path(*value.parts[: value.parts.index(marker)])
    return value


def _relative(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def base_ciks(manifest_path: str, root: Path) -> tuple[dict, Path, set[str]]:
    manifest, artifact_path = resolve_manifest(manifest_path, artifacts_root=str(root))
    with FinalizedArtifact(artifact_path) as artifact:
        ciks = artifact.distinct_values("cik")
    return manifest, artifact_path, ciks


def write_worklist(
    rows: list[TargetRow],
    *,
    options: RunOptions,
    source_snapshot_id: str,
    base_manifest: dict,
    root: Path,
) -> tuple[Path, dict]:
    from .paths import resolve_metadata_paths

    metadata_paths = resolve_metadata_paths(env={"ARTIFACTS_ROOT": str(root)})
    worklist_root = metadata_paths.worklist_root(options.run_id)
    worklist_root.mkdir(parents=True, exist_ok=True)
    path = worklist_root / "worklist.parquet"
    records = [
        {
            "cik_padded": row.cik_padded,
            "name": row.name,
            "source_row": row.source_row,
            "work_reason": "missing_from_finalized_metadata",
            "source_snapshot_id": source_snapshot_id,
            "base_metadata_manifest_id": base_manifest["artifact_id"],
        }
        for row in rows
    ]
    table = pa.Table.from_pylist(records, schema=WORKLIST_SCHEMA)
    write_table_atomic(
        table, path, expected_rows=len(records), expected_schema=WORKLIST_SCHEMA
    )
    digest = file_sha256(path)
    manifest = {
        "manifest_kind": "metadata_augmentation_worklist",
        "manifest_schema_version": SCHEMA_VERSION,
        "artifact_id": artifact_id(
            dataset="metadata_augmentation_worklist",
            phase="metadata",
            schema_version=SCHEMA_VERSION,
            artifact_sha256=digest,
        ),
        "dataset": "metadata_augmentation_worklist",
        "producer_phase": "metadata",
        "run_id": options.run_id,
        "schema_version": SCHEMA_VERSION,
        "artifact_path": path.relative_to(root).as_posix(),
        "storage_format": "parquet",
        "byte_count": path.stat().st_size,
        "artifact_sha256": digest,
        "row_count": len(records),
        "upstream_artifact_ids": [base_manifest["artifact_id"], source_snapshot_id],
        "provenance": {"work_reason": "missing_from_finalized_metadata"},
    }
    atomic_write_json(
        path.with_name(path.name + ".manifest.json"), manifest, indent=None
    )
    return path, manifest


def load_plan_rows(options: RunOptions, plan: dict) -> tuple[list[TargetRow], dict]:
    if not plan.get("augmentation"):
        return read_input_manifest(options.input_path, limit=options.limit)
    worklist_path = Path(plan["worklist_path"])
    if not worklist_path.is_absolute():
        worklist_path = (
            artifacts_root(options.base_metadata_manifest or options.artifacts_dir)
            / worklist_path
        )
    if file_sha256(worklist_path) != plan.get("worklist_sha256"):
        raise ValueError("augmentation worklist hash mismatch; regenerate the plan")
    rows = load_worklist(worklist_path)
    return rows, {
        "fingerprint": plan.get("input_fingerprint", ""),
        "row_count": len(rows),
        "malformed": [],
        "duplicates": [],
    }


def output_paths(options: RunOptions) -> tuple[Path, Path, Path, Path]:
    from .paths import resolve_metadata_paths

    root = artifacts_root(options.base_metadata_manifest or options.artifacts_dir)
    metadata_paths = resolve_metadata_paths(env={"ARTIFACTS_ROOT": str(root)})
    output_root = metadata_paths.snapshots_dir / options.run_id
    return (
        root,
        output_root / "submission_metadata_delta.parquet",
        output_root / "submission_metadata.parquet",
        output_root / "snapshot.json",
    )


def discover_source_manifests(root: str | Path) -> list[dict]:
    """List published company-ticker source manifests, latest first."""
    from .paths import resolve_metadata_paths

    metadata_paths = resolve_metadata_paths(env={"ARTIFACTS_ROOT": str(root)})
    directories = (metadata_paths.source_manifest_dir("company_tickers"),)
    entries: list[dict] = []
    seen: set[str] = set()
    for directory in directories:
        for path in sorted(directory.glob("*.json")):
            path_key = str(path)
            if path_key in seen:
                continue
            seen.add(path_key)
            try:
                manifest = load_json(path)
            except (OSError, ValueError):
                continue
            if manifest.get("manifest_kind") != "metadata_source_snapshot":
                continue
            snapshot_id = str(manifest.get("snapshot_id", ""))
            entries.append(
                {
                    "manifest_path": str(path),
                    "snapshot_id": snapshot_id,
                    "retrieved_at": str(manifest.get("retrieved_at", "")),
                    "listing_row_count": int(manifest.get("listing_row_count", 0)),
                    "unique_cik_count": int(manifest.get("unique_cik_count", 0)),
                }
            )
    entries.sort(key=lambda item: item["retrieved_at"], reverse=True)
    return entries


def discover_base_metadata_manifests(root: str | Path) -> list[dict]:
    """List finalized metadata manifests usable as augmentation bases."""
    from .paths import resolve_metadata_paths

    entries: list[dict] = []
    for manifest in find_manifests(
        "submission_metadata", phase="metadata", artifacts_root=str(root)
    ):
        path = root / manifest_relative_path(
            phase="metadata",
            dataset="submission_metadata",
            artifact_id_value=manifest["artifact_id"],
            partition=manifest.get("partition", ""),
        )
        entries.append(
            {
                "kind": "final",
                "manifest_path": str(path),
                "row_count": int(manifest.get("row_count", 0)),
                "artifact_sha256": str(manifest.get("artifact_sha256", "")),
                "run_id": str(manifest.get("run_id", "")),
            }
        )
    metadata_paths = resolve_metadata_paths(env={"ARTIFACTS_ROOT": str(root)})
    snapshot_dir = metadata_paths.snapshots_dir
    for path in sorted(snapshot_dir.glob("*/snapshot.json")):
        try:
            snapshot = load_json(path)
        except (OSError, ValueError):
            continue
        if snapshot.get("manifest_kind") != "submission_metadata_snapshot":
            continue
        entries.append(
            {
                "kind": "snapshot",
                "manifest_path": str(path),
                "row_count": int(snapshot.get("row_count", 0)),
                "artifact_sha256": str(snapshot.get("full_artifact_sha256", "")),
                "run_id": str(snapshot.get("snapshot_id", "")),
            }
        )
    entries.sort(key=lambda item: item["manifest_path"])
    return entries


def _quote(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def publish_snapshot(
    options: RunOptions,
    delta_report: MergeReport,
    delta_path: Path,
    full_path_override: Path | None = None,
) -> MergeReport:
    from .paths import resolve_metadata_paths

    root, _default_delta_path, default_full_path, _snapshot_manifest_path = (
        output_paths(options)
    )
    metadata_paths = resolve_metadata_paths(env={"ARTIFACTS_ROOT": str(root)})
    base_manifest, base_path = resolve_manifest(
        options.base_metadata_manifest, artifacts_root=str(root)
    )

    resources = derive_resources()
    base = FinalizedArtifact(
        base_path
        if base_path.is_file() and base_path.suffix == ".parquet"
        else base_manifest,
        artifacts_root=root,
        threads=resources.threads,
        memory_limit=resources.memory_limit,
        temp_directory=resources.temp_directory,
    )
    delta = FinalizedArtifact(
        delta_path,
        artifacts_root=root,
        threads=resources.threads,
        memory_limit=resources.memory_limit,
        temp_directory=resources.temp_directory,
    )
    try:
        base_count = base.count()
        delta_count = delta.count()
        if base.columns != delta.columns:
            raise MergeError("base and delta metadata artifacts have different schemas")
        overlap = base.key_overlap_count(delta_path, "cik")
        if overlap:
            raise MergeError(
                f"augmentation merge found {overlap} CIKs in both base and delta"
            )
        full_path = (
            full_path_override if full_path_override is not None else default_full_path
        )
        if full_path is not None and not Path(full_path).exists():
            Path(full_path).parent.mkdir(parents=True, exist_ok=True)
            base.copy_union(delta_path, full_path)
    finally:
        base.close()
        delta.close()

    # Move/copy delta part to snapshot parts directory
    delta_part_path = (
        metadata_paths.snapshot_parts_dir(options.run_id, "shard-0000")
        / "part-000.parquet"
    )
    delta_part_path.parent.mkdir(parents=True, exist_ok=True)
    if str(delta_path.resolve()) != str(delta_part_path.resolve()):
        tmp_d = delta_part_path.with_suffix(".tmp")
        shutil.copyfile(str(delta_path), str(tmp_d))
        os.replace(str(tmp_d), str(delta_part_path))

    delta_hash = file_sha256(str(delta_part_path))
    delta_part_entry = {
        "path": str(delta_part_path.relative_to(root)),
        "artifact_sha256": delta_hash,
        "row_count": delta_count,
        "byte_count": delta_part_path.stat().st_size,
        "shard_id": "shard-0000",
    }

    # Resolve base parts
    base_parts = []
    if "resolved_parts" in base_manifest:
        base_parts = list(base_manifest["resolved_parts"])
    else:
        base_parts = [
            {
                "path": str(base_path.relative_to(root)),
                "artifact_sha256": base_manifest.get("artifact_sha256")
                or file_sha256(str(base_path)),
                "row_count": base_count,
                "byte_count": base_path.stat().st_size if base_path.is_file() else 0,
                "shard_id": "shard-0000",
            }
        ]

    resolved_parts = base_parts + [delta_part_entry]
    full_count = base_count + delta_count

    delta_manifest = make_manifest(
        dataset="submission_metadata",
        phase="metadata",
        run_id=options.run_id,
        schema_version=SCHEMA_VERSION,
        artifact_path=str(delta_part_path),
        artifacts_root=str(root),
        row_count=delta_count,
        upstream=(base_manifest["artifact_id"],),
        provenance={"report_source": "augmentation_delta"},
    )
    publish_manifest(delta_manifest, artifacts_root=str(root))

    snapshot_manifest_data = make_snapshot_manifest(
        snapshot_id=options.run_id,
        parent_snapshot_id=base_manifest.get(
            "snapshot_id", base_manifest.get("artifact_id")
        ),
        schema_version=SCHEMA_VERSION,
        resolved_parts=resolved_parts,
        added_parts=[delta_part_entry],
        effective_cik_count=full_count,
        plan_id=options.run_id,
        dataset="submission_metadata",
        phase="metadata",
        provenance={
            "report_source": "augmented_snapshot",
            "delta_artifact_sha256": delta_hash,
            "source_manifest": options.source_manifest,
            "base_metadata_manifest": options.base_metadata_manifest,
        },
    )
    manifest_path = publish_snapshot_manifest(
        snapshot_manifest_data,
        artifacts_root=root,
        set_current=True,
    )

    delta_report.output_path = str(manifest_path)
    delta_report.artifact_sha256 = file_sha256(str(manifest_path))
    delta_report.row_count = full_count
    delta_report.report_source = "augmented_snapshot"
    atomic_write_json(
        merge_report_path_in(options.artifacts_dir),
        delta_report.to_dict(),
        indent=2,
        sort_keys=True,
    )
    return delta_report


__all__ = [
    "artifacts_root",
    "base_ciks",
    "discover_base_metadata_manifests",
    "discover_source_manifests",
    "load_plan_rows",
    "output_paths",
    "publish_snapshot",
    "write_worklist",
]
