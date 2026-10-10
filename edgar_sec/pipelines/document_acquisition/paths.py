"""Resolved project and run paths for document acquisition."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import edgar_sec.foundation.runtime.fixtures as foundation_fixtures
from edgar_sec.foundation.runtime.paths import (
    ProjectPaths,
    RUN_LOCK_FILE,
    RUN_MANIFEST_FILE,
    TRANSIENT_DIR,
    resolve_paths,
    snapshots_root,
    transient_dataset_root,
    transient_dir,
    validate_safe_id,
)
from edgar_sec.infra.storage.review.paths import (
    ReviewPaths,
    review_run_paths,
    review_runs_root,
)
from edgar_sec.pipelines.document_planning.paths import resolve_document_planning_paths

DATASET = "document_acquisition"
RUN_STATE_FILE = "state.sqlite"
RUN_CANCELLED_FILE = "cancelled.json"
RUN_STAGING_DIR = "staging"
WORK_ORDER_DIR = "work_order"


@dataclass(frozen=True, slots=True)
class AcquisitionPaths:
    project: ProjectPaths

    @property
    def artifacts_root(self) -> Path:
        return self.project.artifacts_root

    @property
    def transient_root(self) -> Path:
        return self.artifacts_root / TRANSIENT_DIR

    @property
    def runtime_root(self) -> Path:
        return self.project.runtime_root

    @property
    def runs_root(self) -> Path:
        return transient_dataset_root(self.artifacts_root, DATASET)

    def target_plan_dir(self, plan_id: str) -> Path:
        return resolve_document_planning_paths(
            artifacts_root=self.artifacts_root
        ).plan_dir(plan_id)

    @property
    def fixtures_root(self) -> Path:
        return foundation_fixtures.fixtures_root(self.artifacts_root, DATASET)

    def fixture_paths(self, fixture_id: str) -> foundation_fixtures.FixturePaths:
        return foundation_fixtures.fixture_paths(
            self.artifacts_root, DATASET, fixture_id
        )

    def fixture_root(self, fixture_id: str) -> Path:
        return self.fixture_paths(fixture_id).root

    def fixture_manifest_path(self, fixture_id: str) -> Path:
        return self.fixture_paths(fixture_id).manifest_path

    def fixture_database_path(self, fixture_id: str) -> Path:
        return self.fixture_paths(fixture_id).storage_path

    @property
    def review_runs_root(self) -> Path:
        return review_runs_root(self.artifacts_root, DATASET)

    def review_paths(self, review_id: str) -> ReviewPaths:
        return review_run_paths(self.artifacts_root, DATASET, review_id)

    @property
    def snapshots_root(self) -> Path:
        return snapshots_root(self.artifacts_root, DATASET)

    def snapshot_root(self, snapshot_id: str) -> Path:
        return self.snapshots_root / validate_safe_id(snapshot_id, "snapshot_id")

    def run_dir(self, run_id: str) -> Path:
        safe_run_id = validate_safe_id(run_id, "run_id")
        return transient_dir(self.artifacts_root, DATASET, safe_run_id)

    def run_manifest_path(self, run_id: str) -> Path:
        return self.run_dir(run_id) / RUN_MANIFEST_FILE

    def work_order_root(self, run_id: str) -> Path:
        return self.run_dir(run_id) / WORK_ORDER_DIR

    def run_state_path(self, run_id: str) -> Path:
        return self.run_dir(run_id) / RUN_STATE_FILE

    def run_lock_path(self, run_id: str) -> Path:
        return self.run_dir(run_id) / RUN_LOCK_FILE

    def run_cancelled_path(self, run_id: str) -> Path:
        return self.run_dir(run_id) / RUN_CANCELLED_FILE

    def run_staging_root(self, run_id: str) -> Path:
        return self.run_dir(run_id) / RUN_STAGING_DIR


def resolve_acquisition_paths(
    repo_root: str | Path | None = None,
    artifacts_root: str | Path | None = None,
) -> AcquisitionPaths:
    root = Path(repo_root).resolve() if repo_root is not None else None
    project = resolve_paths(root)
    if artifacts_root is not None:
        project = ProjectPaths(
            repo_root=project.repo_root,
            artifacts_root=Path(artifacts_root).resolve(),
            uploads_root=project.uploads_root,
        )
    return AcquisitionPaths(project)


__all__ = [
    "DATASET",
    "RUN_CANCELLED_FILE",
    "RUN_STAGING_DIR",
    "RUN_STATE_FILE",
    "WORK_ORDER_DIR",
    "AcquisitionPaths",
    "resolve_acquisition_paths",
]
