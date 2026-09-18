"""Execution engine for Phase 2 filing catalog snapshot materialization."""

from __future__ import annotations

import hashlib
import importlib
import json
import logging
import shutil
from collections.abc import Callable
from contextlib import suppress
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
    build_batch_query,
    build_profile_query,
    build_sources_query,
    partition_key,
    register_identity_functions,
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


def _stream_form_batches(
    artifact: FinalizedDataset,
    snapshot_dir: Path,
    source_hash: str,
    catalog_id: str,
    report: dict | None,
    source_batch_size: int,
    progress: Callable[[dict], None] | None,
) -> tuple[dict[str, int], int, dict[str, int]]:
    ciks = [
        r[0]
        for r in artifact.run(
            f"SELECT cik FROM {artifact.relation} WHERE cik IS NOT NULL ORDER BY cik"
        )
    ]
    batch_count = (
        max(1, (len(ciks) + source_batch_size - 1) // source_batch_size) if ciks else 1
    )
    staging_dir = snapshot_dir / ".staging_partitions"
    staging_dir.mkdir(parents=True, exist_ok=True)

    raw_forms = [
        r[0]
        for r in artifact.run(
            f"SELECT DISTINCT unnest(filings).form FROM {artifact.relation} WHERE filings IS NOT NULL"
        )
        if r[0]
    ]
    all_keys = sorted({partition_key(f) for f in raw_forms if f})
    _emit(
        progress,
        {
            "type": "merge_stage",
            "stage": "discover_forms",
            "forms": len(all_keys),
            "total_units": len(all_keys) + 5,
            "source_batch_size": source_batch_size,
        },
    )

    path_source_stats: dict[str, int] = {}
    metadata = {
        "source_artifact_sha256": source_hash,
        "input_fingerprint": report.get("input_fingerprint", "") if report else "",
        "schema_version": SOURCE.SCHEMA_VERSION,
        "catalog_id": catalog_id,
    }
    metadata_sql = ", ".join(f"'{v}' AS \"{k}\"" for k, v in metadata.items())
    batch_sql = build_batch_query(artifact.relation, metadata_sql)

    for b_idx in range(batch_count):
        b_start = b_idx * source_batch_size
        b_end = min(b_start + source_batch_size, len(ciks))
        b_ciks = ciks[b_start:b_end]
        start_cik, end_cik = b_ciks[0], b_ciks[-1]
        batch_staging_dir = staging_dir / f"batch_{b_idx}"

        artifact.copy_partitioned_query(
            batch_sql,
            str(batch_staging_dir),
            partition_by="form_partition_key",
            parameters=[start_cik, end_cik],
        )
        _emit(
            progress,
            {
                "type": "batch_done",
                "batch": b_idx + 1,
                "total_batches": batch_count,
                "cik_start": start_cik,
                "cik_end": end_cik,
                "rows": b_end - b_start,
                "total_ciks": len(ciks),
                "ciks_done": b_end,
            },
        )
        force_reclaim_memory()

    counts: dict[str, int] = {}
    target_root = snapshot_dir / "filing_targets"
    target_root.mkdir(parents=True, exist_ok=True)
    form_keys = sorted(
        {
            p.name.split("=", 1)[1]
            for p in staging_dir.glob("batch_*/form_partition_key=*")
            if "=" in p.name
        }
    )

    for part_key in form_keys:
        dest_dir = target_root / f"form={part_key}"
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_file = dest_dir / "data.parquet"
        parquet_files = sorted(
            staging_dir.glob(f"batch_*/form_partition_key={part_key}/*.parquet")
        )
        if not parquet_files:
            continue
        if len(parquet_files) == 1:
            shutil.copyfile(parquet_files[0], dest_file)
        else:
            file_list = ", ".join(f"'{p}'" for p in parquet_files)
            concat_q = (
                f"COPY (SELECT * FROM read_parquet([{file_list}])) "
                f"TO '{dest_file}' (FORMAT PARQUET, COMPRESSION 'zstd')"
            )
            artifact.run(concat_q)

        res = artifact.run(
            f"SELECT form, COUNT(*) FROM read_parquet('{dest_file}') GROUP BY form"
        )
        for form_name, row_cnt in res:
            counts[str(form_name)] = int(row_cnt)
            _emit(
                progress,
                {
                    "type": "merge_stage",
                    "stage": f"targets:{form_name}",
                    "rows": int(row_cnt),
                },
            )

    shutil.rmtree(staging_dir, ignore_errors=True)
    force_reclaim_memory()
    return counts, batch_count, path_source_stats


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
    base_catalog_manifest: str | None = None,
) -> dict:
    """Materialize Phase 2 filing catalog snapshot from Phase 1 metadata snapshot."""
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
        register_identity_functions(artifact)
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
        snapshot_dir = (
            Path(output_root).resolve() / snapshot_id
            if output_root
            else fp.catalog_snapshot_dir(snapshot_id)
        )

        if snapshot_dir.exists():
            shutil.rmtree(snapshot_dir, ignore_errors=True)
        snapshot_dir.mkdir(parents=True, exist_ok=True)

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

        # Stage 2: Batched Form Streaming
        counts, batch_count, path_source_stats = _stream_form_batches(
            artifact=artifact,
            snapshot_dir=snapshot_dir,
            source_hash=source_hash,
            catalog_id=catalog_id,
            report=report,
            source_batch_size=source_batch_size,
            progress=progress,
        )

        # Stage 3: Occurrence Sources
        target_root = snapshot_dir / "filing_targets"
        target_files = sorted(target_root.glob("form=*/data.parquet"))
        sources_path = snapshot_dir / "filing_occurrence_sources.parquet"
        source_count = 0
        if target_files:
            sources_query = build_sources_query(target_files)
            source_count = artifact.copy_query(sources_query, str(sources_path))
        _emit(
            progress,
            {
                "type": "merge_stage",
                "stage": "occurrence_sources",
                "rows": source_count,
            },
        )
        force_reclaim_memory()

        # Stage 4: Snapshot Manifest & Active Pointer
        try:
            rel_dir = snapshot_dir.relative_to(artifacts_root)
        except ValueError:
            rel_dir = snapshot_dir

        manifest = {
            "manifest_kind": "filing_catalog_snapshot",
            "producer_phase": "filing_extraction",
            "dataset": "filing_catalog",
            "snapshot_id": snapshot_id,
            "catalog_id": catalog_id,
            "source_artifact_sha256": source_hash,
            "upstream_snapshot_id": handoff.get("snapshot_id") if handoff else None,
            "schema_version": SCHEMA_VERSION,
            "target_rows": sum(counts.values()),
            "form_count": len(counts),
            "company_profiles_rows": profile_count,
            "occurrence_sources_rows": source_count,
            "form_partitions": counts,
            "path_source_statistics": path_source_stats,
            "snapshot_path": str(rel_dir / "snapshot.manifest.json"),
            "company_profiles_path": str(rel_dir / "company_profiles.parquet"),
            "occurrence_sources_path": str(
                rel_dir / "filing_occurrence_sources.parquet"
            ),
            "filing_targets_dir": str(rel_dir / "filing_targets"),
            "source_batch_size": source_batch_size,
            "batch_count": batch_count,
        }
        manifest_path = snapshot_dir / "snapshot.manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        if not output_root or str(artifacts_root) in str(snapshot_dir):
            with suppress(Exception):
                update_current_snapshot_pointer(
                    snapshot_id=snapshot_id,
                    manifest_path=manifest["snapshot_path"],
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
