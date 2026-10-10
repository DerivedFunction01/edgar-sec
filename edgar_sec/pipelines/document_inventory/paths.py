"""Single owner for document-inventory artifact, runtime, and transient paths."""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path

import edgar_sec.foundation.runtime.fixtures as foundation_fixtures
import edgar_sec.foundation.runtime.paths as foundation_paths
from edgar_sec.infra.storage.dag.paths import DAGPaths
from edgar_sec.pipelines.filing_catalog.paths import (
    FilingCatalogPaths,
    LOCATOR_GROUPS_FILE,
    PLAN_TARGETS_DIR,
    REQUIRED_PLAN_FILES,
    SEED_FILERS_FILE,
    form_partition_name,
    resolve_filing_catalog_paths,
)

__all__ = [
    "ATTEMPT_PREFIX",
    "CHUNKS_DIR",
    "COHORT_ACCESSIONS_FILE",
    "COHORT_SOURCES_FILE",
    "DATASET",
    "ENTRIES_FILE",
    "FIXTURE_DATABASE_FILE",
    "InventoryPaths",
    "InventoryRunPaths",
    "LOCK_FILE",
    "MANIFEST_FILE",
    "OUTCOMES_FILE",
    "POINTER_FILE",
    "PROJECTION_MANIFEST_FILE",
    "PROJECTION_STAGING_DIR",
    "PUBLICATION_DIR",
    "PUBLICATION_OUTCOMES_FILE",
    "PUBLICATION_ENTRIES_FILE",
    "PUBLICATION_SOURCES_FILE",
    "NEW_ACCESSIONS_FILE",
    "KNOWN_ACCESSIONS_FILE",
    "CANDIDATE_ENTRIES_FILE",
    "CANCELLED_FILE",
    "FilingCatalogPaths",
    "LOCATOR_GROUPS_FILE",
    "PLAN_TARGETS_DIR",
    "REQUIRED_PLAN_FILES",
    "SEED_FILERS_FILE",
    "PUBLICATION_LOCK_FILE",
    "NEW_SOURCES_FILE",
    "RUN_MANIFEST_FILE",
    "REVIEW_CASES_DIR",
    "REVIEW_MANIFEST_FILE",
    "REVIEW_RUNS_DIR",
    "SNAPSHOT_PART_PREFIX",
    "WORK_ORDER_FILE",
    "inventory_run_paths",
    "inventory_paths",
    "snapshot_id_for",
    "form_partition_name",
    "resolve_filing_catalog_paths",
    "resolve_index_fixture_paths",
]

#: Dataset name under ``artifacts_root`` and ``transient/``.
DATASET = "document_inventory"

#: Files inside one attempt directory.
OUTCOMES_FILE = "outcomes.parquet"
ENTRIES_FILE = "entries.parquet"
MANIFEST_FILE = "manifest.json"
SNAPSHOT_PART_PREFIX = "part-"

#: Files at the run root.
RUN_MANIFEST_FILE = "run_manifest.json"
LOCK_FILE = "run.lock"
CANCELLED_FILE = "cancelled.json"
PUBLICATION_LOCK_FILE = foundation_paths.PUBLICATION_LOCK_FILE

#: Pointer naming the current committed attempt for a chunk.
POINTER_FILE = "current.json"
PROGRESS_DIR = "progress"
PROGRESS_POINTER_FILE = "current.json"

#: Directory names under a chunk.
CHUNKS_DIR = foundation_paths.CHUNKS_DIR

#: Prefix for one immutable attempt directory inside a chunk.
ATTEMPT_PREFIX = "attempt-"

#: S5-owned staging directory inside a run.
PUBLICATION_DIR = "publication"
PUBLICATION_OUTCOMES_FILE = "publication_outcomes.parquet"
PUBLICATION_ENTRIES_FILE = "publication_entries.parquet"
PUBLICATION_SOURCES_FILE = "publication_sources.parquet"
NEW_ACCESSIONS_FILE = "new_accessions.parquet"
KNOWN_ACCESSIONS_FILE = "known_accessions.parquet"
CANDIDATE_ENTRIES_FILE = "candidate_entries.parquet"
NEW_SOURCES_FILE = "new_sources.parquet"

#: Published snapshot root, owned by S5, separate from transient state.
FIXTURE_DATABASE_FILE = "index_fixtures.sqlite"
REVIEW_RUNS_DIR = foundation_paths.REVIEW_RUNS_DIR
REVIEW_CASES_DIR = foundation_paths.CASES_DIR
REVIEW_MANIFEST_FILE = "manifest.jsonl"
WORK_ORDER_FILE = "work_order.parquet"
COHORT_ACCESSIONS_FILE = "cohort_accessions.parquet"
COHORT_SOURCES_FILE = "cohort_sources.parquet"
PROJECTION_MANIFEST_FILE = "projection_manifest.json"
PROJECTION_STAGING_DIR = "projection-staging"


def _validate_id(value: str, label: str) -> str:
    return foundation_paths.validate_safe_id(value, label)


class InventoryPaths:
    """Validated paths for inventory-owned fixture and snapshot artifacts."""

    __slots__ = ("artifacts_root",)

    def __init__(self, artifacts_root: Path | str) -> None:
        self.artifacts_root = Path(artifacts_root).resolve()

    @property
    def snapshots_root(self) -> Path:
        return self.artifacts_root / DATASET / foundation_paths.SNAPSHOTS_DIR

    @property
    def fixtures_root(self) -> Path:
        return foundation_fixtures.fixtures_root(self.artifacts_root, DATASET)

    def fixture_root(self, fixture_id: str) -> Path:
        return self.index_fixture_paths(fixture_id).root

    def index_fixture_paths(self, fixture_id: str) -> foundation_fixtures.FixturePaths:
        return foundation_fixtures.fixture_paths(
            self.artifacts_root, DATASET, fixture_id, FIXTURE_DATABASE_FILE
        )

    def fixture_manifest_path(self, fixture_id: str) -> Path:
        return self.index_fixture_paths(fixture_id).manifest_path

    def fixture_database_path(self, fixture_id: str) -> Path:
        return self.index_fixture_paths(fixture_id).storage_path

    def snapshot_root(self, snapshot_id: str) -> Path:
        return self.snapshots_root / _validate_id(snapshot_id, "snapshot_id")

    @property
    def review_runs_root(self) -> Path:
        return self.artifacts_root / DATASET / REVIEW_RUNS_DIR

    def review_run_root(self, review_id: str) -> Path:
        return self.review_runs_root / _validate_id(review_id, "review_id")

    def review_manifest_path(self, review_id: str) -> Path:
        return self.review_run_root(review_id) / REVIEW_MANIFEST_FILE

    @property
    def catalog_file(self) -> Path:
        """SQLite DAG catalog database for published inventory snapshots."""
        return DAGPaths(self.snapshots_root).catalog_file

    @property
    def publication_lock_path(self) -> Path:
        return self.snapshots_root / PUBLICATION_LOCK_FILE

    @property
    def projection_staging_root(self) -> Path:
        return (
            self.artifacts_root
            / foundation_paths.TRANSIENT_DIR
            / DATASET
            / PROJECTION_STAGING_DIR
        )

    @property
    def transient_root(self) -> Path:
        return self.artifacts_root / foundation_paths.TRANSIENT_DIR / DATASET

    def broker_socket_path(self, socket_id: str) -> Path:
        """Out-of-tree runtime socket; intentionally omitted. :no-docgen:"""
        safe_id = _validate_id(socket_id, "socket_id")
        identity = hashlib.sha256(
            f"{self.artifacts_root}:{safe_id}".encode("utf-8")
        ).hexdigest()[:24]
        return (
            Path(tempfile.gettempdir())
            / f"edgar-sec-{os.getuid()}"
            / f"{identity}.sock"
        )


class InventoryRunPaths:
    """Validated path methods for one inventory run.

    Every ID accepted here is validated as a single safe path component, so no
    method accepts an arbitrary relative path that could escape the run tree.
    """

    __slots__ = ("artifacts_root", "run_id", "run_root")

    def __init__(self, artifacts_root: Path, run_id: str) -> None:
        self.artifacts_root = Path(artifacts_root)
        self.run_id = _validate_id(run_id, "run_id")
        self.run_root = foundation_paths.transient_dir(
            self.artifacts_root, DATASET, self.run_id
        )

    # --- run-level -------------------------------------------------------

    @property
    def snapshots_root(self) -> Path:
        """Published snapshot root, owned by S5."""
        return InventoryPaths(self.artifacts_root).snapshots_root

    def run_manifest_path(self) -> Path:
        return self.run_root / RUN_MANIFEST_FILE

    def lock_path(self) -> Path:
        return self.run_root / LOCK_FILE

    def cancelled_path(self) -> Path:
        return self.run_root / CANCELLED_FILE

    def publication_dir(self) -> Path:
        """S5-owned staging directory inside this run."""
        return self.run_root / PUBLICATION_DIR

    def work_order_path(self) -> Path:
        return self.run_root / WORK_ORDER_FILE

    def cohort_accessions_path(self) -> Path:
        return self.run_root / COHORT_ACCESSIONS_FILE

    def cohort_sources_path(self) -> Path:
        return self.run_root / COHORT_SOURCES_FILE

    def projection_manifest_path(self) -> Path:
        return self.run_root / PROJECTION_MANIFEST_FILE

    # --- chunk-level -----------------------------------------------------

    def chunk_dir(self, chunk_id: str) -> Path:
        return self.run_root / CHUNKS_DIR / _validate_id(chunk_id, "chunk_id")

    def chunk_pointer_path(self, chunk_id: str) -> Path:
        return self.chunk_dir(chunk_id) / POINTER_FILE

    def progress_dir(self, chunk_id: str) -> Path:
        return self.chunk_dir(chunk_id) / PROGRESS_DIR

    def progress_pointer_path(self, chunk_id: str) -> Path:
        return self.progress_dir(chunk_id) / PROGRESS_POINTER_FILE

    def progress_database_path(self, chunk_id: str, attempt_id: str) -> Path:
        safe_attempt = _validate_id(attempt_id, "attempt_id")
        return self.progress_dir(chunk_id) / f"progress-{safe_attempt}.duckdb"

    def attempt_dir(self, chunk_id: str, attempt_id: str) -> Path:
        safe_attempt = _validate_id(attempt_id, "attempt_id")
        return self.chunk_dir(chunk_id) / f"{ATTEMPT_PREFIX}{safe_attempt}"

    def attempt_outcomes_path(self, chunk_id: str, attempt_id: str) -> Path:
        return self.attempt_dir(chunk_id, attempt_id) / OUTCOMES_FILE

    def attempt_entries_path(self, chunk_id: str, attempt_id: str) -> Path:
        return self.attempt_dir(chunk_id, attempt_id) / ENTRIES_FILE

    def attempt_manifest_path(self, chunk_id: str, attempt_id: str) -> Path:
        return self.attempt_dir(chunk_id, attempt_id) / MANIFEST_FILE


def inventory_run_paths(artifacts_root: Path | str, run_id: str) -> InventoryRunPaths:
    """Construct validated inventory run paths from an artifacts root and run id."""
    return InventoryRunPaths(Path(artifacts_root), run_id)


def inventory_paths(artifacts_root: Path | str) -> InventoryPaths:
    """Construct inventory artifact paths from the selected artifacts root."""
    return InventoryPaths(artifacts_root)


def snapshot_id_for(parent_snapshot_id: str | None, digest: str) -> str:
    """Derive an immutable snapshot id from its parent and content digest."""
    content = f"{parent_snapshot_id or ''}:{digest}"
    return f"snapshot-{hashlib.sha256(content.encode('utf-8')).hexdigest()[:16]}"


def resolve_index_fixture_paths(
    artifacts_root: Path | str | None, fixture_id: str
) -> foundation_fixtures.FixturePaths:
    root = (
        Path(artifacts_root)
        if artifacts_root is not None
        else foundation_paths.resolve_paths().artifacts_root
    )
    return inventory_paths(root).index_fixture_paths(fixture_id)
