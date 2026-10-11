"""Resolved paths and SQL relations for feature snapshot artifacts."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from edgar_sec.domain.filing_catalog.schemas import (
    LOCATOR_FEATURE_COLUMNS,
    OCCURRENCE_DYNAMIC_COLUMNS,
    OCCURRENCE_FEATURE_COLUMNS,
    OCCURRENCE_INDEPENDENT_COLUMNS,
)
from edgar_sec.engine.selection.paths import FEATURE_MANIFEST_FILE
from edgar_sec.infra.storage.duckdb import sql_literal


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
    manifest: Path
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
    root = Path(snapshot_dir).resolve()
    manifest_path = root / FEATURE_MANIFEST_FILE
    recorded = json.loads(manifest_path.read_text(encoding="utf-8"))
    artifact_keys = (
        "occurrence_parts",
        "locator_band_parts",
        "lifecycle_parts",
        "locator_feature_parts",
    )
    if any(not recorded.get(key) for key in artifact_keys):
        raise ValueError(f"feature snapshot manifest is incomplete: {manifest_path}")
    return SnapshotPaths(
        snapshot_dir=root,
        manifest=manifest_path,
        occurrence_parts=tuple(Path(path) for path in recorded["occurrence_parts"]),
        locator_band_parts=tuple(Path(path) for path in recorded["locator_band_parts"]),
        lifecycle_parts=tuple(Path(path) for path in recorded["lifecycle_parts"]),
        locator_feature_parts=tuple(
            Path(path) for path in recorded["locator_feature_parts"]
        ),
    )


__all__ = ["SnapshotPaths", "load_snapshot_paths"]
