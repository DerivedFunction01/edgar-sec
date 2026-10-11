"""Execute full and append-delta feature snapshot builds."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from edgar_sec.engine.selection.paths import (
    FEATURE_MANIFEST_FILE,
    LIFECYCLE_FILE,
    LOCATOR_BANDS_FILE,
    LOCATOR_FEATURES_FILE,
    OCCURRENCE_INDEPENDENT_FILE,
)
from edgar_sec.engine.selection.snapshot import SnapshotPaths
from edgar_sec.foundation.hashing import file_sha256
from edgar_sec.infra.storage.atomic import atomic_write_text
from edgar_sec.infra.storage.duckdb import connect, sql_literal


def build_snapshot(builder: Any, feature_schema_version: str) -> SnapshotPaths:
    forms = sorted(set(builder.policy.forms))
    if not forms:
        raise ValueError("no forms configured in policy")

    snapshot_dir = builder.snapshot_dir(forms)
    manifest_path = snapshot_dir / FEATURE_MANIFEST_FILE
    if builder._is_reusable(manifest_path):
        return builder.paths_for(snapshot_dir)
    manifest_path.unlink(missing_ok=True)

    active_parts = builder._target_part_files()
    incremental = builder._is_parent_compatible() and bool(builder.delta_target_parts)
    new_parts = builder._new_target_part_files(incremental)
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    independent_path = snapshot_dir / OCCURRENCE_INDEPENDENT_FILE
    locator_bands_path = snapshot_dir / LOCATOR_BANDS_FILE
    lifecycle_path = snapshot_dir / LIFECYCLE_FILE
    locator_features_path = snapshot_dir / LOCATOR_FEATURES_FILE

    parent_manifest: dict[str, Any] = {}
    if incremental and builder.parent_feature_manifest is not None:
        parent_manifest = json.loads(
            builder.parent_feature_manifest.read_text(encoding="utf-8")
        )
    occurrence_parts = [
        *(Path(path) for path in parent_manifest.get("occurrence_parts", [])),
        independent_path,
    ]
    locator_band_parts = [
        *(Path(path) for path in parent_manifest.get("locator_band_parts", []))
    ]
    lifecycle_parts = [
        *(Path(path) for path in parent_manifest.get("lifecycle_parts", []))
    ]
    locator_feature_parts = [
        *(Path(path) for path in parent_manifest.get("locator_feature_parts", []))
    ]

    counts: dict[str, int] = {}
    with connect() as con:
        active_union = builder._target_union(forms, active_parts)
        new_union = builder._target_union(forms, new_parts)
        counts["independent_occurrence_rows"] = builder._write_occurrence_independent(
            con, new_union, snapshot_dir
        )
        prior_anchors = parent_manifest.get("size_anchors", {})
        delta_form_families = [
            str(row[0])
            for row in con.execute(
                "SELECT DISTINCT "
                f"{builder._form_family_sql('form')} "
                f"FROM ({new_union}) ORDER BY 1"
            ).fetchall()
        ]
        current_anchors = dict(prior_anchors) if incremental else {}
        anchor_rows = con.execute(
            builder._size_band_anchor_sql(
                active_union, delta_form_families if incremental else None
            )
        ).fetchall()
        if incremental:
            for family in delta_form_families:
                current_anchors.pop(family, None)
        current_anchors.update({str(row[0]): float(row[1]) for row in anchor_rows})
        changed_families = sorted(
            family
            for family in (delta_form_families if incremental else current_anchors)
            if current_anchors.get(family) != prior_anchors.get(family)
        )
        delta_locator_keys = [
            str(row[0])
            for row in con.execute(
                f"SELECT DISTINCT document_locator_key FROM ({new_union}) "
                "WHERE document_locator_key IS NOT NULL ORDER BY 1"
            ).fetchall()
        ]
        counts["locator_band_rows"] = builder._write_locator_bands(
            con,
            active_union,
            snapshot_dir,
            families=changed_families if incremental else None,
            locator_keys=delta_locator_keys if incremental else None,
            anchor_families=delta_form_families if incremental else None,
            full=not incremental,
        )
        locator_band_parts.append(locator_bands_path)

        delta_max_year = builder._global_max_year(con, new_union)
        year_candidates = [
            value
            for value in (
                parent_manifest.get("global_max_year") if incremental else None,
                delta_max_year,
            )
            if value is not None
        ]
        global_max_year = max(year_candidates) if year_candidates else None
        lifecycle_is_global = (
            not incremental or parent_manifest.get("global_max_year") != global_max_year
        )
        changed_ciks_sql = (
            None
            if lifecycle_is_global
            else f"SELECT DISTINCT source_cik FROM ({new_union})"
        )
        counts["lifecycle_rows"] = builder._write_lifecycle(
            con, active_union, snapshot_dir, global_max_year, changed_ciks_sql
        )
        lifecycle_parts.append(lifecycle_path)

        occurrence_relation = SnapshotPaths(
            snapshot_dir=snapshot_dir,
            manifest=manifest_path,
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
        counts["locator_features"] = builder._write_locator_features(
            con, snapshot_dir, occurrence_relation, affected_keys_sql
        )
        locator_feature_parts.append(locator_features_path)

    manifest = {
        "snapshot_id": snapshot_dir.name,
        "feature_schema_version": feature_schema_version,
        "feature_signature": builder.feature_signature(forms),
        "profile_path": str(builder.profile_path),
        "profile_sha256": file_sha256(builder.profile_path),
        "family_index_id": builder.family_index_id,
        "corpus_id": builder.policy.corpus_id,
        "occurrence_parts": [str(path) for path in occurrence_parts],
        "locator_band_parts": [str(path) for path in locator_band_parts],
        "lifecycle_parts": [str(path) for path in lifecycle_parts],
        "locator_feature_parts": [str(path) for path in locator_feature_parts],
        "size_anchors": current_anchors,
        "global_max_year": global_max_year,
        "parent_snapshot": (
            str(builder.parent_feature_manifest)
            if incremental and builder.parent_feature_manifest is not None
            else ""
        ),
        "incremental": incremental,
        "counts": counts,
    }
    atomic_write_text(
        manifest_path,
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
    )
    return builder.paths_for(snapshot_dir)
