"""Directory layout for the datasets pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import edgar_sec.foundation.runtime.paths as foundation_paths
from edgar_sec.foundation.runtime.paths import (
    ProjectPaths,
    resolve_paths,
    transient_dir,
    validate_safe_id,
)
from edgar_sec.infra.storage.dag.paths import DAGPaths

DATASETS_DIR = "datasets"
BULK_ARCHIVES_DIR = "bulk_archives"
STORE_FILE = "datasets.duckdb"


@dataclass(frozen=True, slots=True)
class DatasetsPaths:
    """Root-scoped datasets layout, independent of any single run."""

    artifacts_root: Path

    @property
    def datasets_root(self) -> Path:
        """Root of the datasets store and its published snapshots."""
        return self.artifacts_root / DATASETS_DIR

    @property
    def store_file(self) -> Path:
        """The DuckDB datasets store."""
        return self.datasets_root / STORE_FILE

    @property
    def bulk_archives_root(self) -> Path:
        """Root of the shared bulk-archive store (all sources, all pipelines)."""
        return self.artifacts_root / BULK_ARCHIVES_DIR

    @property
    def snapshots_root(self) -> Path:
        """Root of published index snapshot directories, and of the pointer."""
        return self.datasets_root / foundation_paths.SNAPSHOTS_DIR

    @property
    def catalog_file(self) -> Path:
        """SQLite DAG catalog database for published index snapshots."""
        return DAGPaths(self.snapshots_root).catalog_file

    def snapshot_dir(self, snapshot_id: str) -> Path:
        """Directory holding one immutable index snapshot."""
        return self.snapshots_root / validate_safe_id(snapshot_id)

    def transient_dir(self, run_id: str) -> Path:
        """Staging directory for one datasets run, never published."""
        return transient_dir(
            self.artifacts_root, DATASETS_DIR, validate_safe_id(run_id)
        )


def resolve_datasets_paths(
    artifacts_root: str | Path | None = None,
    project_paths: ProjectPaths | None = None,
) -> DatasetsPaths:
    """Resolve the datasets layout from an explicit root or the project default."""
    if artifacts_root is not None:
        return DatasetsPaths(artifacts_root=Path(artifacts_root).resolve())
    if project_paths is not None:
        return DatasetsPaths(artifacts_root=project_paths.artifacts_root)
    return DatasetsPaths(artifacts_root=resolve_paths().artifacts_root)


__all__ = [
    "BULK_ARCHIVES_DIR",
    "DATASETS_DIR",
    "STORE_FILE",
    "DatasetsPaths",
    "resolve_datasets_paths",
]
