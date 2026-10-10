"""Materialize an immutable filing-catalog snapshot from a metadata snapshot.
Four guards are invariants: a transient source is refused, the column list must
exactly match the source schema, an existing snapshot is never overwritten, and
parts must be CIK-disjoint.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any, NamedTuple

from edgar_sec.domain.filing_catalog.schemas import (
    PROFILE_SCHEMA_VERSION,
    SCHEMA_VERSION,
    TARGET_SCHEMA,
    TARGET_SCHEMA_VERSION,
)
from edgar_sec.domain.submissions.schemas import (
    SCHEMA_VERSION as SOURCE_SCHEMA_VERSION,
)
from edgar_sec.domain.submissions.schemas import SUBMISSION_METADATA_SCHEMA
from edgar_sec.foundation.hashing import file_sha256
from edgar_sec.foundation.runtime.memory import reclaim
from edgar_sec.foundation.runtime.progress import ProgressCallback, emit_progress
from edgar_sec.foundation.runtime.settings.parquet import resolve_row_group_size
from edgar_sec.infra.storage.duckdb import (
    connect,
    copy_query_to_parquet,
    sql_literal,
    sql_path_list,
)
from edgar_sec.infra.storage.parquet import read_parquet_schema
from datetime import UTC, datetime
from edgar_sec.infra.storage.dag.catalog import DAGCatalog
from edgar_sec.infra.storage.dag.manifest import (
    DAGNodeManifest,
    ParentRef,
    PartDescriptor,
    ordered_parts_fingerprint,
)
from edgar_sec.infra.storage.dag.publication import publish_node
from edgar_sec.pipelines.filing_catalog.materialization import (
    build_delta_profile_query,
    build_delta_unnest_query,
    build_part_unnest_query,
    build_profile_query,
)
from edgar_sec.pipelines.filing_catalog.paths import (
    PIPELINE_DIR,
    SNAPSHOT_FILE,
    TARGETS_DIR,
    resolve_filing_catalog_paths,
    resolve_metadata_paths,
    target_part_name,
)

FALLBACK_POLICY_VERSION = "1.1.0"

TRANSIENT_SOURCE_PARTS = frozenset({"chunks", "checkpoints", "workers"})
TARGET_SORT_ORDER = "source_part_order"


class CatalogError(RuntimeError):
    """A catalog invariant was violated and materialization cannot proceed."""


def _catalog_id(source_hash: str) -> str:
    """Derive a content-addressed catalog id from the source dataset."""
    payload = json.dumps(
        [source_hash, SOURCE_SCHEMA_VERSION, SCHEMA_VERSION, FALLBACK_POLICY_VERSION],
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


class SourceDataset(NamedTuple):
    """A resolved Phase 1 source: the parts to read and their handoff metadata."""

    paths: tuple[Path, ...]
    handoff: dict[str, Any] | None

    @property
    def part_count(self) -> int:
        return len(self.paths)

    @property
    def first(self) -> Path:
        """The first part; used for messages and single-file display."""
        return self.paths[0]


def resolve_source(
    source_artifact: str | os.PathLike[str] | None,
    source_snapshot_id: str | None = None,
    *,
    source_artifacts_root: str | os.PathLike[str] | None = None,
) -> SourceDataset:
    """Resolve an explicit Parquet source, catalogued snapshot, or current pointer."""
    if source_artifact is not None and source_snapshot_id:
        raise CatalogError(
            "source_artifact and source_snapshot_id are mutually exclusive"
        )
    if source_snapshot_id:
        return _source_from_snapshot(source_snapshot_id, source_artifacts_root)
    if source_artifact is not None:
        candidate = Path(source_artifact).resolve()
        if not candidate.is_file():
            raise CatalogError(f"source artifact does not exist: {candidate}")
        return SourceDataset(paths=(candidate,), handoff=None)
    return _source_from_pointer(source_artifacts_root)


def _source_from_snapshot(
    snapshot_id: str,
    source_artifacts_root: str | os.PathLike[str] | None = None,
) -> SourceDataset:
    metadata_paths = resolve_metadata_paths(source_artifacts_root)
    try:
        catalog = DAGCatalog(metadata_paths.snapshots_root, read_only=True)
        node = catalog.get_manifest(snapshot_id)
        if node is None:
            raise ValueError(f"snapshot is not catalogued: {snapshot_id}")
        paths = catalog.resolve_relation(
            snapshot_id,
            "submissions",
            relative_to=metadata_paths.snapshot_dir(snapshot_id),
        )
    except (FileNotFoundError, ValueError) as exc:
        raise CatalogError(str(exc)) from exc
    handoff = {
        **node.metadata,
        "snapshot_id": node.snapshot_id,
        "parts_digest": node.logical_fingerprint,
        "parent_snapshot_id": node.parent_snapshot_id
        or str(node.metadata.get("parent_snapshot_id") or ""),
        "parents": [parent.to_dict() for parent in node.parents],
    }
    return SourceDataset(paths=paths, handoff=handoff)


def _source_from_pointer(
    source_artifacts_root: str | os.PathLike[str] | None = None,
) -> SourceDataset:
    metadata_paths = resolve_metadata_paths(source_artifacts_root)
    try:
        meta_catalog = DAGCatalog(metadata_paths.snapshots_root, read_only=True)
    except FileNotFoundError as exc:
        raise CatalogError(
            "no Phase 1 snapshot is published; run 'metadata merge' first or "
            "pass source_artifact explicitly"
        ) from exc
    ptr = meta_catalog.read_pointer()
    if not ptr or not ptr.get("snapshot_id"):
        raise CatalogError(
            "no Phase 1 snapshot is published; run 'metadata merge' first or "
            "pass source_artifact explicitly"
        )
    snapshot_id = str(ptr["snapshot_id"])
    return _source_from_snapshot(snapshot_id, source_artifacts_root)


def _guard_not_transient(source: SourceDataset) -> None:
    """Refuse a transient source work unit as a catalog source."""
    for path in source.paths:
        if any(part in TRANSIENT_SOURCE_PARTS for part in path.parts):
            raise CatalogError(
                f"Phase 2 requires a finalized artifact, not a chunk/checkpoint: {path}"
            )


def _guard_schema_matches(source: SourceDataset) -> None:
    """Every part must be exactly the declared source dataset."""
    expected = SUBMISSION_METADATA_SCHEMA.names
    for path in source.paths:
        actual = read_parquet_schema(path).names
        if list(actual) != list(expected):
            missing = [name for name in expected if name not in actual]
            extra = [name for name in actual if name not in expected]
            raise CatalogError(
                f"source artifact columns do not match submission_metadata schema; "
                f"missing={missing} unexpected={extra} ({path})"
            )


def _guard_ciks_are_disjoint(source: SourceDataset) -> None:
    """Each CIK must appear in exactly one source part.
    The target pass dedupes within a part only, so a CIK spanning two would publish
    the same ``occurrence_id`` twice. The check prunes to the ``cik`` column.
    """
    if source.part_count < 2:
        return
    listed = sql_path_list([str(path) for path in source.paths])
    with connect() as con:
        conflicts = con.execute(
            f"""
            SELECT cik, count(DISTINCT filename) AS parts
            FROM read_parquet({listed}, filename = true)
            WHERE cik IS NOT NULL
            GROUP BY cik
            HAVING count(DISTINCT filename) > 1
            ORDER BY cik
            LIMIT 5
            """
        ).fetchall()
    if conflicts:
        detail = ", ".join(f"{cik} in {parts} parts" for cik, parts in conflicts)
        raise CatalogError(
            "source parts share CIKs; a sharded catalog would publish duplicate "
            f"occurrence ids across shards ({detail})"
        )


def materialize(
    source_artifact: str | os.PathLike[str] | None = None,
    output_root: str | os.PathLike[str] | None = None,
    *,
    source_snapshot_id: str | None = None,
    source_artifacts_root: str | os.PathLike[str] | None = None,
    progress: ProgressCallback = None,
    row_group_size: int | None = None,
    branch_name: str = "main",
    expected_branch_tip: str | None = None,
) -> dict[str, Any]:
    """Materialize one immutable filing-catalog snapshot via a CAS pointer update.
    Durable writes advance branch_name under the shared publication lock.
    """
    groups = resolve_row_group_size(row_group_size)

    source = resolve_source(
        source_artifact,
        source_snapshot_id,
        source_artifacts_root=source_artifacts_root,
    )
    _guard_not_transient(source)
    _guard_schema_matches(source)
    _guard_ciks_are_disjoint(source)
    emit_progress(
        progress,
        {
            "type": "merge_stage",
            "stage": "validate_source",
            "parts": source.part_count,
        },
    )

    paths = resolve_filing_catalog_paths(output_root)
    # A catalog id must identify the dataset, not one file of it: an
    # upstream id wins, else the ordered part digests do, so two layouts holding
    # the same rows resolve to the same catalog.
    source_hash = str(
        (source.handoff or {}).get("parts_digest") or ""
    ) or ordered_parts_fingerprint([file_sha256(path) for path in source.paths])
    snapshot_id = str(
        (source.handoff or {}).get("snapshot_id") or _catalog_id(source_hash)
    )
    catalog_id = snapshot_id

    # An explicit output_root is read as an artifacts root, so a catalog written
    # to a scratch directory can be planned from that same directory.
    durable = output_root is None
    final_dir = paths.snapshot_dir(catalog_id)
    staging_dir = paths.transient_catalog_dir(catalog_id)

    # Immutability applies to both publication modes: an existing
    # destination snapshot is never overwritten.
    if final_dir.exists():
        raise CatalogError(
            f"immutable catalog snapshot already exists: {final_dir}; prune it or "
            "advance to a new upstream snapshot"
        )

    handoff = source.handoff or {}
    parent_id = str(
        handoff.get("parent_snapshot_id")
        or handoff.get("parent_id")
        or (
            handoff["parents"][0]["snapshot_id"]
            if handoff.get("parents") and len(handoff["parents"]) > 0
            else ""
        )
        or ""
    )
    dag_catalog = DAGCatalog(paths.snapshots_root)
    is_delta = bool(parent_id and dag_catalog.has_snapshot(parent_id))
    base_node = dag_catalog.get_manifest(parent_id) if is_delta else None
    base_target_paths: list[str] = []
    if is_delta:
        active_base = dag_catalog.get_active_parts(parent_id, {"filing_targets"})
        base_target_paths = [
            str(paths.snapshots_root / p.path)
            if not Path(p.path).is_absolute()
            else str(p.path)
            for p in active_base
        ]

    if staging_dir.exists():
        shutil.rmtree(staging_dir, ignore_errors=True)
    staging_dir.mkdir(parents=True, exist_ok=True)

    with connect() as con:
        con.execute(
            "CREATE OR REPLACE TEMP VIEW source AS SELECT * FROM "
            f"read_parquet({sql_path_list([str(path) for path in source.paths])})"
        )

        base_profiles_file = (
            paths.snapshot_profiles_file(parent_id) if is_delta else None
        )
        if base_profiles_file is not None and base_profiles_file.is_file():
            profile_query = build_delta_profile_query("source", str(base_profiles_file))
        else:
            profile_query = build_profile_query("source")
        profiles_path = staging_dir / SNAPSHOT_FILE
        profile_count = copy_query_to_parquet(con, profile_query, profiles_path, groups)
        emit_progress(
            progress,
            {
                "type": "merge_stage",
                "stage": "company_profiles",
                "rows": profile_count,
            },
        )

    reclaim()

    targets_dir = staging_dir / TARGETS_DIR
    if targets_dir.exists():
        shutil.rmtree(targets_dir)
    targets_dir.mkdir(parents=True, exist_ok=True)

    part_metadata: list[dict[str, Any]] = []
    form_counts: dict[str, int] = {}
    total_target_rows = 0
    with connect() as con:
        for index, source_path in enumerate(source.paths):
            shard_name = target_part_name(index)
            shard_path = targets_dir / shard_name
            if is_delta and base_target_paths:
                query = build_delta_unnest_query(str(source_path), base_target_paths)
            else:
                query = build_part_unnest_query(str(source_path))
            rows = copy_query_to_parquet(con, query, shard_path, groups)
            total_target_rows += rows
            part_metadata.append(
                {
                    "path": f"{TARGETS_DIR}/{shard_name}",
                    "part_index": index,
                    "source_part": str(source_path),
                    "row_count": rows,
                    "artifact_sha256": file_sha256(shard_path),
                }
            )
            for form_name, count in con.execute(
                f"SELECT form, COUNT(*) FROM read_parquet({sql_literal(str(shard_path))}) "
                f"WHERE form IS NOT NULL GROUP BY form ORDER BY form"
            ).fetchall():
                form_counts[str(form_name)] = form_counts.get(str(form_name), 0) + int(
                    count
                )
            emit_progress(
                progress,
                {
                    "type": "merge_stage",
                    "stage": f"filing_targets:{shard_name}",
                    "rows": rows,
                },
            )
            reclaim()

    reclaim()

    snapshot_metadata = {
        "snapshot_kind": "filing_catalog",
        "catalog_id": catalog_id,
        "snapshot_id": snapshot_id,
        "source_artifact": str(source.first),
        "source_parts": [str(path) for path in source.paths],
        "source_part_count": source.part_count,
        "source_sha256": source_hash,
        "schema_version": SCHEMA_VERSION,
        "target_schema_version": TARGET_SCHEMA_VERSION,
        "profile_schema_version": PROFILE_SCHEMA_VERSION,
        "profile_row_count": profile_count,
        "target_row_count": total_target_rows,
        "target_columns": TARGET_SCHEMA.names,
        "form_counts": form_counts,
        "parts": part_metadata,
        "target_part_count": len(part_metadata),
        "sort_order": TARGET_SORT_ORDER,
        "pipeline": PIPELINE_DIR,
    }
    target_descriptors = [
        PartDescriptor(
            path=f"{catalog_id}/{TARGETS_DIR}/{target_part_name(i)}",
            sha256=p["artifact_sha256"],
            row_count=p["row_count"],
            byte_size=Path(targets_dir / target_part_name(i)).stat().st_size,
        )
        for i, p in enumerate(part_metadata)
    ]
    profile_descriptors = [
        PartDescriptor(
            path=f"{catalog_id}/{SNAPSHOT_FILE}",
            sha256=file_sha256(profiles_path),
            row_count=profile_count,
            byte_size=profiles_path.stat().st_size,
        )
    ]
    parent_refs: list[ParentRef] = []
    if is_delta and base_node is not None:
        parent_sha = dag_catalog.get_manifest_sha256(parent_id) or ""
        parent_refs.append(ParentRef(snapshot_id=parent_id, manifest_sha256=parent_sha))
        checkpoint_anchor_id = base_node.checkpoint_anchor_id or parent_id
        lineage_depth = base_node.lineage_depth + 1
        kind = "delta"
    else:
        checkpoint_anchor_id = catalog_id
        lineage_depth = 0
        kind = "checkpoint"

    dag_manifest = DAGNodeManifest(
        snapshot_id=catalog_id,
        kind=kind,
        parents=tuple(parent_refs),
        checkpoint_anchor_id=checkpoint_anchor_id,
        lineage_depth=lineage_depth,
        created_at=datetime.now(UTC).isoformat(timespec="seconds"),
        relations={
            "filing_targets": tuple(target_descriptors),
            "company_profiles": tuple(profile_descriptors),
        },
        logical_fingerprint=(
            ordered_parts_fingerprint(
                [str(part["artifact_sha256"]) for part in part_metadata]
            )
            if part_metadata
            else source_hash
        ),
        schema_versions={
            "filing_targets": TARGET_SCHEMA_VERSION,
            "company_profiles": PROFILE_SCHEMA_VERSION,
        },
        metadata={
            "source_artifact": str(source.first),
            "source_parts": [str(path) for path in source.paths],
            "form_counts": form_counts,
            "source_sha256": source_hash,
            "catalog_schema_version": SCHEMA_VERSION,
        },
    )

    final_dir.parent.mkdir(parents=True, exist_ok=True)
    os.replace(staging_dir, final_dir)
    if durable:
        if expected_branch_tip is None:
            current = dag_catalog.read_pointer(branch_name)
            expected_branch_tip = str(current["snapshot_id"]) if current else None
        publish_node(
            paths.snapshots_root,
            dag_manifest,
            expected_parent_id=expected_branch_tip,
            branch_name=branch_name,
        )
    else:
        dag_catalog.record_node(dag_manifest)

    emit_progress(
        progress,
        {
            "type": "merge_stage",
            "stage": "publish",
            "catalog_id": catalog_id,
            "rows": total_target_rows,
        },
    )
    return snapshot_metadata


__all__ = [
    "FALLBACK_POLICY_VERSION",
    "TARGET_SORT_ORDER",
    "TRANSIENT_SOURCE_PARTS",
    "CatalogError",
    "materialize",
    "resolve_source",
]
