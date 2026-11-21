"""Directory layout for the table-classification pipeline."""

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

PIPELINE_DIR = "table_classification"
PLAN_FILE_NAME = foundation_paths.PLAN_FILE_NAME


@dataclass(frozen=True, slots=True)
class ClassificationPaths:
    """Root-scoped classification layout, independent of any one plan."""

    artifacts_root: Path

    @property
    def pipeline_root(self) -> Path:
        """Root of the classification pipeline's own artifacts."""
        return self.artifacts_root / PIPELINE_DIR

    @property
    def plans_root(self) -> Path:
        """Root of published classification plan bundles."""
        return self.pipeline_root / foundation_paths.PLANS_DIR

    @property
    def snapshots_root(self) -> Path:
        """Root of published classification snapshots (the store lane's)."""
        return self.pipeline_root / foundation_paths.SNAPSHOTS_DIR

    def plan_dir(self, plan_id: str) -> Path:
        """Directory holding one immutable plan bundle."""
        return self.plans_root / validate_safe_id(plan_id, "plan_id")

    def plan_manifest_path(self, plan_id: str) -> Path:
        """Manifest file inside one plan bundle."""
        return self.plan_dir(plan_id) / PLAN_FILE_NAME

    def plan_relation_path(self, plan_id: str, relation: str) -> Path:
        """Parquet file for one relation inside one plan bundle."""
        return self.plan_dir(plan_id) / f"{validate_safe_id(relation)}.parquet"

    def transient_dir(self, plan_id: str) -> Path:
        """Staging directory for one plan's run, never published."""
        return transient_dir(
            self.artifacts_root, PIPELINE_DIR, validate_safe_id(plan_id, "plan_id")
        )

    def work_dir(self, plan_id: str, work_item_id: str) -> Path:
        """Staging directory holding one work item's output relations."""
        return (
            self.transient_dir(plan_id)
            / "work"
            / validate_safe_id(work_item_id, "work_item_id")
        )

    def merged_dir(self, plan_id: str) -> Path:
        """Staging directory holding one run's merged output relations."""
        return self.transient_dir(plan_id) / "merged"


def resolve_classification_paths(
    artifacts_root: str | Path | None = None,
    project_paths: ProjectPaths | None = None,
) -> ClassificationPaths:
    """Resolve the classification layout from a root or the project default."""
    if artifacts_root is not None:
        return ClassificationPaths(artifacts_root=Path(artifacts_root).resolve())
    if project_paths is not None:
        return ClassificationPaths(artifacts_root=project_paths.artifacts_root)
    return ClassificationPaths(artifacts_root=resolve_paths().artifacts_root)


__all__ = [
    "PIPELINE_DIR",
    "PLAN_FILE_NAME",
    "ClassificationPaths",
    "resolve_classification_paths",
]
