"""Single owner for document-inventory artifact, runtime, and transient paths."""

from __future__ import annotations

import re
from pathlib import Path

import edgar_sec.foundation.runtime.fixtures as foundation_fixtures
import edgar_sec.foundation.runtime.paths as foundation_paths

__all__ = [
    "ATTEMPT_PREFIX",
    "CHUNK_MANIFEST_FILE",
    "CHUNKS_DIR",
    "DATASET",
    "ENTRIES_FILE",
    "FIXTURE_DATABASE_FILE",
    "InventoryPaths",
    "InventoryRunPaths",
    "LOCK_FILE",
    "OUTCOMES_FILE",
    "POINTER_FILE",
    "PUBLICATION_DIR",
    "PUBLICATION_OUTCOMES_FILE",
    "PUBLICATION_ENTRIES_FILE",
    "PUBLICATION_SOURCES_FILE",
    "NEW_ACCESSIONS_FILE",
    "KNOWN_ACCESSIONS_FILE",
    "CANDIDATE_ENTRIES_FILE",
    "NEW_SOURCES_FILE",
    "RUN_MANIFEST_FILE",
    "REVIEW_CASES_DIR",
    "REVIEW_MANIFEST_FILE",
    "REVIEW_RUNS_DIR",
    "WORK_ORDER_FILE",
    "inventory_run_paths",
    "inventory_paths",
    "resolve_index_fixture_paths",
]

#: Dataset name under ``artifacts_root`` and ``transient/``.
DATASET = "document_inventory"

#: Files inside one attempt directory.
OUTCOMES_FILE = "outcomes.parquet"
ENTRIES_FILE = "entries.parquet"
CHUNK_MANIFEST_FILE = "manifest.json"

#: Files at the run root.
RUN_MANIFEST_FILE = "run_manifest.json"
LOCK_FILE = "run.lock"

#: Pointer naming the current committed attempt for a chunk.
POINTER_FILE = "current.json"

#: Directory names under a chunk.
CHUNKS_DIR = "chunks"

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
REVIEW_RUNS_DIR = "review-runs"
REVIEW_CASES_DIR = "cases"
REVIEW_MANIFEST_FILE = "manifest.jsonl"
WORK_ORDER_FILE = "work_order.parquet"

_ID_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


def _validate_id(value: str, label: str) -> str:
    """Return ``value`` if it is a single safe path component, else raise."""
    if not isinstance(value, str) or not value or not _ID_RE.match(value):
        raise ValueError(f"invalid {label}: {value!r}")
    if value in (".", ".."):
        raise ValueError(f"invalid {label}: {value!r}")
    return value


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

    def current_snapshot_pointer(self) -> Path:
        return foundation_paths.current_pointer_path(self.snapshots_root)

    @property
    def runtime_root(self) -> Path:
        return foundation_paths.runtime_root(self.artifacts_root)

    def broker_socket_path(self, socket_id: str) -> Path:
        return self.runtime_root / f"{_validate_id(socket_id, 'socket_id')}.sock"


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

    def publication_dir(self) -> Path:
        """S5-owned staging directory inside this run."""
        return self.run_root / PUBLICATION_DIR

    def work_order_path(self) -> Path:
        return self.run_root / WORK_ORDER_FILE

    # --- chunk-level -----------------------------------------------------

    def chunk_dir(self, chunk_id: str) -> Path:
        return self.run_root / CHUNKS_DIR / _validate_id(chunk_id, "chunk_id")

    def chunk_pointer_path(self, chunk_id: str) -> Path:
        return self.chunk_dir(chunk_id) / POINTER_FILE

    def attempt_dir(self, chunk_id: str, attempt_id: str) -> Path:
        safe_attempt = _validate_id(attempt_id, "attempt_id")
        return self.chunk_dir(chunk_id) / f"{ATTEMPT_PREFIX}{safe_attempt}"

    def attempt_outcomes_path(self, chunk_id: str, attempt_id: str) -> Path:
        return self.attempt_dir(chunk_id, attempt_id) / OUTCOMES_FILE

    def attempt_entries_path(self, chunk_id: str, attempt_id: str) -> Path:
        return self.attempt_dir(chunk_id, attempt_id) / ENTRIES_FILE

    def attempt_manifest_path(self, chunk_id: str, attempt_id: str) -> Path:
        return self.attempt_dir(chunk_id, attempt_id) / CHUNK_MANIFEST_FILE

    # --- shared pointer --------------------------------------------------

    @staticmethod
    def current_pointer_path(snapshots_root: Path) -> Path:
        """Return the published-snapshot pointer for the inventory dataset."""
        return foundation_paths.current_pointer_path(Path(snapshots_root))


def inventory_run_paths(artifacts_root: Path | str, run_id: str) -> InventoryRunPaths:
    """Construct validated inventory run paths from an artifacts root and run id."""
    return InventoryRunPaths(Path(artifacts_root), run_id)


def inventory_paths(artifacts_root: Path | str) -> InventoryPaths:
    """Construct inventory artifact paths from the selected artifacts root."""
    return InventoryPaths(artifacts_root)


def resolve_index_fixture_paths(
    artifacts_root: Path | str | None, fixture_id: str
) -> foundation_fixtures.FixturePaths:
    root = (
        Path(artifacts_root)
        if artifacts_root is not None
        else foundation_paths.resolve_paths().artifacts_root
    )
    return inventory_paths(root).index_fixture_paths(fixture_id)
