"""Execute full and append-delta feature snapshot builds."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from edgar_sec.engine.selection.paths import (
    LIFECYCLE_FILE,
    LOCATOR_BANDS_FILE,
    LOCATOR_FEATURES_FILE,
    OCCURRENCE_INDEPENDENT_FILE,
)
from edgar_sec.engine.selection.snapshot import (
    LIFECYCLE_RELATION,
    LOCATOR_BANDS_RELATION,
    LOCATOR_FEATURES_RELATION,
    OCCURRENCE_RELATION,
    SnapshotPaths,
    feature_branch_name,
)
from edgar_sec.foundation.hashing import file_sha256, sha256_text
from edgar_sec.foundation.serialization import canonical_json
from edgar_sec.foundation.runtime.paths import SNAPSHOTS_DIR
from edgar_sec.foundation.runtime.progress import ProgressCallback, emit_progress
from edgar_sec.infra.storage.dag.catalog import DAGCatalog
from edgar_sec.infra.storage.duckdb import connect, sql_literal
from edgar_sec.infra.storage.dag.manifest import (
    DAGNodeManifest,
    ParentRef,
    PartDescriptor,
)
from edgar_sec.infra.storage.parquet import count_parquet_rows, read_parquet_key_bounds


def _part_descriptor(
    path: Path, snapshots_root: Path, key_column: str
) -> PartDescriptor:
    path = path.resolve()
    relative = path.relative_to(snapshots_root.resolve()).as_posix()
    key_min, key_max = read_parquet_key_bounds(path, key_column)
    return PartDescriptor(
        path=relative,
        sha256=file_sha256(path),
        row_count=count_parquet_rows(path),
        byte_size=path.stat().st_size,
        key_min=key_min,
        key_max=key_max,
    )


def build_snapshot(
    builder: Any,
    feature_schema_version: str,
    progress: ProgressCallback = None,
) -> SnapshotPaths:
    forms = sorted(set(builder.policy.forms))
    if not forms:
        raise ValueError("no forms configured in policy")

    active_parts = builder._target_part_files()
    snapshot_dir = builder.snapshot_dir(forms)
    snapshot_id = snapshot_dir.name

    if builder._is_reusable(snapshot_id):
        return builder.paths_for(snapshot_dir)

    incremental = builder._is_parent_compatible() and bool(builder.delta_target_parts)
    new_parts = builder._new_target_part_files(incremental)
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    independent_path = snapshot_dir / OCCURRENCE_INDEPENDENT_FILE
    locator_bands_path = snapshot_dir / LOCATOR_BANDS_FILE
    lifecycle_path = snapshot_dir / LIFECYCLE_FILE
    locator_features_path = snapshot_dir / LOCATOR_FEATURES_FILE

    parent_snapshot: SnapshotPaths | None = None
    parent_manifest: dict[str, Any] = {}
    if incremental:
        parent_snapshot = builder._load_parent_snapshot()
        parent_manifest = parent_snapshot.manifest
    occurrence_parts = [
        *(parent_snapshot.occurrence_parts if parent_snapshot is not None else ()),
        independent_path,
    ]
    locator_band_parts = [
        *(parent_snapshot.locator_band_parts if parent_snapshot is not None else ())
    ]
    lifecycle_parts = [
        *(parent_snapshot.lifecycle_parts if parent_snapshot is not None else ())
    ]
    locator_feature_parts = [
        *(parent_snapshot.locator_feature_parts if parent_snapshot is not None else ())
    ]

    counts: dict[str, int] = {}
    with connect() as con:
        active_union = builder._target_union(forms, active_parts)
        new_union = builder._target_union(forms, new_parts)
        emit_progress(
            progress,
            {"type": "merge_stage", "stage": "feature_occurrences_started"},
        )
        counts["independent_occurrence_rows"] = builder._write_occurrence_independent(
            con, new_union, snapshot_dir
        )
        emit_progress(
            progress,
            {
                "type": "merge_stage",
                "stage": "feature_occurrences_complete",
                "rows": counts["independent_occurrence_rows"],
            },
        )
        prior_anchors = parent_manifest.get("size_anchors", {})
        emit_progress(
            progress,
            {"type": "merge_stage", "stage": "feature_anchors_started"},
        )
        delta_form_families_sql = (
            "SELECT DISTINCT "
            f"{builder._form_family_sql('form')} AS form_family "
            f"FROM ({new_union})"
        )
        current_anchors = dict(prior_anchors) if incremental else {}
        if incremental:
            con.execute(
                "CREATE TEMP TABLE prior_size_anchors "
                "(form_family VARCHAR PRIMARY KEY, median_size DOUBLE)"
            )
            if prior_anchors:
                con.executemany(
                    "INSERT INTO prior_size_anchors VALUES (?, ?)",
                    (
                        (str(family), float(anchor))
                        for family, anchor in prior_anchors.items()
                    ),
                )
            con.execute(
                "CREATE TEMP TABLE delta_size_anchors AS "
                + builder._size_band_anchor_sql(active_union, delta_form_families_sql)
            )
            family_cursor = con.execute(
                f"SELECT form_family FROM ({delta_form_families_sql}) "
                "ORDER BY form_family"
            )
            while family_row := family_cursor.fetchone():
                family = str(family_row[0])
                current_anchors.pop(family, None)
            anchor_cursor = con.execute(
                "SELECT form_family, median_size FROM delta_size_anchors "
                "ORDER BY form_family"
            )
            while anchor_row := anchor_cursor.fetchone():
                current_anchors[str(anchor_row[0])] = float(anchor_row[1])
            con.execute(
                "CREATE TEMP TABLE changed_size_families AS "
                f"SELECT d.form_family FROM ({delta_form_families_sql}) d "
                "LEFT JOIN delta_size_anchors a USING (form_family) "
                "LEFT JOIN prior_size_anchors p USING (form_family) "
                "WHERE p.form_family IS NULL OR a.form_family IS NULL "
                "OR a.median_size IS DISTINCT FROM p.median_size"
            )
            changed_families_sql = "SELECT form_family FROM changed_size_families"
            anchor_families_sql = delta_form_families_sql
        else:
            anchor_cursor = con.execute(builder._size_band_anchor_sql(active_union))
            while anchor_row := anchor_cursor.fetchone():
                current_anchors[str(anchor_row[0])] = float(anchor_row[1])
            changed_families_sql = None
            anchor_families_sql = None
        emit_progress(
            progress,
            {
                "type": "merge_stage",
                "stage": "feature_anchors_complete",
                "anchor_count": len(current_anchors),
            },
        )
        delta_locator_keys_sql = (
            f"SELECT DISTINCT document_locator_key FROM ({new_union}) "
            "WHERE document_locator_key IS NOT NULL"
        )
        emit_progress(
            progress,
            {"type": "merge_stage", "stage": "feature_locator_bands_started"},
        )
        counts["locator_band_rows"] = builder._write_locator_bands(
            con,
            active_union,
            snapshot_dir,
            family_relation_sql=changed_families_sql,
            locator_keys_sql=delta_locator_keys_sql if incremental else None,
            anchor_family_relation_sql=anchor_families_sql,
            full=not incremental,
        )
        emit_progress(
            progress,
            {
                "type": "merge_stage",
                "stage": "feature_locator_bands_complete",
                "rows": counts["locator_band_rows"],
            },
        )
        locator_band_parts.append(locator_bands_path)

        emit_progress(
            progress,
            {"type": "merge_stage", "stage": "feature_max_year_started"},
        )
        delta_max_year = builder._global_max_year(con, new_union)
        prior_max_year = parent_manifest.get("global_max_year") if incremental else None
        global_max_year = max(
            (year for year in (prior_max_year, delta_max_year) if year is not None),
            default=None,
        )
        emit_progress(
            progress,
            {
                "type": "merge_stage",
                "stage": "feature_max_year_complete",
                "year": global_max_year,
            },
        )
        lifecycle_is_global = (
            not incremental or parent_manifest.get("global_max_year") != global_max_year
        )
        changed_ciks_sql = (
            None
            if lifecycle_is_global
            else f"SELECT DISTINCT source_cik FROM ({new_union})"
        )
        emit_progress(
            progress,
            {"type": "merge_stage", "stage": "feature_lifecycle_started"},
        )
        counts["lifecycle_rows"] = builder._write_lifecycle(
            con, active_union, snapshot_dir, global_max_year, changed_ciks_sql
        )
        emit_progress(
            progress,
            {
                "type": "merge_stage",
                "stage": "feature_lifecycle_complete",
                "rows": counts["lifecycle_rows"],
            },
        )
        lifecycle_parts.append(lifecycle_path)

        occurrence_relation = SnapshotPaths(
            snapshot_dir=snapshot_dir,
            manifest={},
            occurrence_parts=tuple(occurrence_parts),
            locator_band_parts=tuple(locator_band_parts),
            lifecycle_parts=tuple(lifecycle_parts),
            locator_feature_parts=tuple(locator_feature_parts)
            or (locator_features_path,),
        ).occurrence_relation
        affected_keys_sql = None
        if incremental and not lifecycle_is_global:
            affected_keys_sql = (
                f"SELECT document_locator_key FROM ({new_union}) "
                "UNION SELECT document_locator_key FROM "
                f"read_parquet({sql_literal(str(locator_bands_path))}) "
                "UNION SELECT o.document_locator_key "
                f"FROM {occurrence_relation} o JOIN "
                f"read_parquet({sql_literal(str(lifecycle_path))}) c "
                "USING (source_cik)"
            )
        emit_progress(
            progress,
            {"type": "merge_stage", "stage": "feature_locator_features_started"},
        )
        counts["locator_features"] = builder._write_locator_features(
            con, snapshot_dir, occurrence_relation, affected_keys_sql
        )
        emit_progress(
            progress,
            {
                "type": "merge_stage",
                "stage": "feature_locator_features_complete",
                "rows": counts["locator_features"],
            },
        )
        locator_feature_parts.append(locator_features_path)

    feature_signature = builder.feature_signature(forms)
    manifest = {
        "artifact_kind": "selection_features",
        "feature_signature": feature_signature,
        "profile_path": str(builder.profile_path),
        "profile_sha256": file_sha256(builder.profile_path),
        "family_index_id": builder.family_index_id,
        "corpus_id": builder.policy.corpus_id,
        "size_anchors": current_anchors,
        "global_max_year": global_max_year,
        "incremental": incremental,
        "counts": counts,
    }

    snapshots_root = builder.output_root / SNAPSHOTS_DIR
    relations = {
        OCCURRENCE_RELATION: (
            _part_descriptor(independent_path, snapshots_root, "occurrence_id"),
        ),
        LOCATOR_BANDS_RELATION: (
            _part_descriptor(
                locator_bands_path, snapshots_root, "document_locator_key"
            ),
        ),
        LIFECYCLE_RELATION: (
            _part_descriptor(lifecycle_path, snapshots_root, "source_cik"),
        ),
        LOCATOR_FEATURES_RELATION: (
            _part_descriptor(
                locator_features_path, snapshots_root, "document_locator_key"
            ),
        ),
    }
    catalog = DAGCatalog(snapshots_root)
    parents: tuple[ParentRef, ...] = ()
    checkpoint_anchor_id = snapshot_id
    lineage_depth = 0
    kind = "checkpoint"
    if incremental and builder.parent_feature_snapshot_id is not None:
        parent_id = builder.parent_feature_snapshot_id
        parent = catalog.get_manifest(parent_id)
        parent_sha256 = catalog.get_manifest_sha256(parent_id)
        if parent is None or parent_sha256 is None:
            raise ValueError(
                f"parent feature node disappeared during build: {parent_id}"
            )
        parents = (ParentRef(parent_id, parent_sha256),)
        checkpoint_anchor_id = parent.checkpoint_anchor_id
        lineage_depth = parent.lineage_depth + 1
        kind = "delta"

    logical_fingerprint = sha256_text(
        canonical_json(
            {
                "metadata": manifest,
                "relations": {
                    name: [part.to_dict() for part in parts]
                    for name, parts in relations.items()
                },
                "parents": [parent.to_dict() for parent in parents],
            }
        )
    )
    node = DAGNodeManifest(
        snapshot_id=snapshot_id,
        kind=kind,
        parents=parents,
        checkpoint_anchor_id=checkpoint_anchor_id,
        lineage_depth=lineage_depth,
        created_at=datetime.now(UTC).isoformat(),
        relations=relations,
        logical_fingerprint=logical_fingerprint,
        schema_versions={"selection_features": feature_schema_version},
        metadata=manifest,
    )
    branch_name = feature_branch_name(feature_signature)
    catalog.publish_node(node, branch_name=branch_name)

    return builder.paths_for(snapshot_dir)
