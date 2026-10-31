"""Resolved paths and SQL relations for feature snapshot artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from edgar_sec.domain.filing_catalog.schemas import (
    LOCATOR_FEATURE_COLUMNS,
    OCCURRENCE_DYNAMIC_COLUMNS,
    OCCURRENCE_FEATURE_COLUMNS,
    OCCURRENCE_INDEPENDENT_COLUMNS,
)
from edgar_sec.foundation.serialization import canonical_hash
from edgar_sec.infra.storage.dag.catalog import DAGCatalog
from edgar_sec.infra.storage.duckdb import sql_literal

OCCURRENCE_RELATION = "selection_occurrence_independent"
LOCATOR_BANDS_RELATION = "selection_locator_bands"
LIFECYCLE_RELATION = "selection_lifecycle"
LOCATOR_FEATURES_RELATION = "selection_locator_features"


def feature_branch_name(feature_signature: dict[str, Any]) -> str:
    """Keep one DAG branch per policy, across source catalog updates."""
    branch_basis = {
        key: value
        for key, value in feature_signature.items()
        if key != "family_index_id"
    }
    return f"features/{canonical_hash(branch_basis)[:32]}"


def _overlay_relation(
    parts: tuple[Path, ...], key: str, columns: tuple[str, ...]
) -> str:
    projections = ", ".join(columns)
    branches = [
        "SELECT "
        f"{projections}, {order} AS part_order "
        f"FROM read_parquet({sql_literal(str(path))})"
        for order, path in enumerate(parts)
    ]
    union = " UNION ALL ".join(branches)
    return (
        "(SELECT "
        f"{projections} FROM ({union}) "
        f"QUALIFY ROW_NUMBER() OVER (PARTITION BY {key} ORDER BY part_order DESC) = 1)"
    )


@dataclass(frozen=True, slots=True)
class SnapshotPaths:
    snapshot_dir: Path
    manifest: dict[str, Any]
    occurrence_parts: tuple[Path, ...]
    locator_band_parts: tuple[Path, ...]
    lifecycle_parts: tuple[Path, ...]
    locator_feature_parts: tuple[Path, ...]

    @property
    def locator_bands(self) -> Path:
        return self.locator_band_parts[-1]

    @property
    def lifecycle(self) -> Path:
        return self.lifecycle_parts[-1]

    @property
    def locator_features(self) -> Path:
        return self.locator_feature_parts[-1]

    @property
    def locator_relation(self) -> str:
        return _overlay_relation(
            self.locator_feature_parts,
            "document_locator_key",
            LOCATOR_FEATURE_COLUMNS,
        )

    @property
    def occurrence_relation(self) -> str:
        band_columns = ("document_locator_key", "size_band")
        lifecycle_columns = (
            "source_cik",
            "has_revival_gap",
            "lifecycle_class",
        )
        bands = _overlay_relation(
            self.locator_band_parts, "document_locator_key", band_columns
        )
        lifecycle = _overlay_relation(
            self.lifecycle_parts, "source_cik", lifecycle_columns
        )
        independent = set(OCCURRENCE_INDEPENDENT_COLUMNS)
        projection = []
        for column in OCCURRENCE_FEATURE_COLUMNS:
            if column in independent:
                projection.append(f"i.{column}")
            elif column == "size_band":
                projection.append("b.size_band")
            elif column == "has_revival_gap":
                projection.append(
                    "COALESCE(l.has_revival_gap, false) AS has_revival_gap"
                )
            else:
                projection.append(
                    "COALESCE(l.lifecycle_class, 'unknown') AS lifecycle_class"
                )
        parts = ", ".join(sql_literal(str(path)) for path in self.occurrence_parts)
        return (
            "(SELECT "
            f"{', '.join(projection)} FROM read_parquet([{parts}]) i "
            f"LEFT JOIN {bands} b USING (document_locator_key) "
            f"LEFT JOIN {lifecycle} l USING (source_cik))"
        )


def load_snapshot_paths(snapshot_dir: str | Path) -> SnapshotPaths:
    """Resolve feature relations from the snapshot's DAG node and ancestors."""
    root = Path(snapshot_dir).resolve()
    snapshot_id = root.name

    try:
        catalog = DAGCatalog(root.parent, read_only=True)
    except FileNotFoundError as exc:
        raise ValueError(f"feature snapshot is not registered: {snapshot_id}") from exc
    node = catalog.get_manifest(snapshot_id)
    if node is None or node.metadata.get("artifact_kind") != "selection_features":
        raise ValueError(f"feature snapshot is not registered: {snapshot_id}")

    feature_metadata = dict(node.metadata)
    feature_schema_version = node.schema_versions.get("selection_features", "")
    feature_kind = node.kind
    parent_id = node.parent_snapshot_id
    occurrence_parts = catalog.resolve_active_relation(
        snapshot_id, OCCURRENCE_RELATION, verify_digests=False
    )
    locator_band_parts = catalog.resolve_active_relation(
        snapshot_id, LOCATOR_BANDS_RELATION, verify_digests=False
    )
    lifecycle_parts = catalog.resolve_active_relation(
        snapshot_id, LIFECYCLE_RELATION, verify_digests=False
    )
    locator_feature_parts = catalog.resolve_active_relation(
        snapshot_id, LOCATOR_FEATURES_RELATION, verify_digests=False
    )
    if not all(
        (occurrence_parts, locator_band_parts, lifecycle_parts, locator_feature_parts)
    ):
        raise ValueError(f"feature snapshot manifest is incomplete: {snapshot_id}")

    manifest = {
        **feature_metadata,
        "snapshot_id": node.snapshot_id,
        "feature_schema_version": feature_schema_version,
        "parent_snapshot": parent_id,
        "incremental": feature_kind == "delta",
    }
    return SnapshotPaths(
        snapshot_dir=root,
        manifest=manifest,
        occurrence_parts=occurrence_parts,
        locator_band_parts=locator_band_parts,
        lifecycle_parts=lifecycle_parts,
        locator_feature_parts=locator_feature_parts,
    )


__all__ = ["SnapshotPaths", "feature_branch_name", "load_snapshot_paths"]
