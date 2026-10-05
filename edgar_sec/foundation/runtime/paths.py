"""Root directory layout resolution for edgar_sec."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .settings import resolve_settings

# Cross-pipeline artifact layout: an immutable dataset under a dataset root, a
# pointer naming what is published, and resumable work under a transient root.
TRANSIENT_DIR = "transient"
CURRENT_DIR = "current"
POINTER_FILE_NAME = "pointer.json"
PLAN_FILE_NAME = "plan.json"
SNAPSHOTS_DIR = "snapshots"
PLANS_DIR = "plans"

# Document storage reuses the same contract; only the dataset name differs.
DOCUMENTS_DATASET = "document_storage"
RUNS_DIR = "runs"
CHECKPOINTS_DIR = "checkpoints"
FIXTURES_DIR = "fixtures"
PAYLOAD_DB_NAME = "fixture.sqlite"
FIXTURE_MANIFEST_NAME = "fixture.manifest.json"
REVIEW_RUNS_DIR = "review-runs"


def current_pointer_path(snapshots_root: Path) -> Path:
    """Return the pointer file naming the currently published snapshot.

    Shared so every dataset resolves "current" identically.
    """
    return snapshots_root / CURRENT_DIR / POINTER_FILE_NAME


def plan_dir(plans_root: Path, plan_id: str) -> Path:
    """Return the directory holding one immutable plan bundle."""
    return plans_root / plan_id


def transient_dir(artifacts_root: Path, dataset: str, run_id: str) -> Path:
    """Return the staging directory for one resumable run of a dataset."""
    return artifacts_root / TRANSIENT_DIR / dataset / run_id


@dataclass(frozen=True, slots=True)
class ProjectPaths:
    """Foundational directory paths for the project workspace."""

    repo_root: Path
    artifacts_root: Path
    uploads_root: Path

    def ensure_directories(self) -> None:
        self.artifacts_root.mkdir(parents=True, exist_ok=True)
        self.uploads_root.mkdir(parents=True, exist_ok=True)
        self.runtime_root.mkdir(parents=True, exist_ok=True)

    @property
    def runtime_root(self) -> Path:
        return self.artifacts_root / "runtime"

    @property
    def broker_socket_path(self) -> Path:
        return self.runtime_root / "sec_broker.sock"

    # --- Document storage -------------------------------------------------

    @property
    def documents_root(self) -> Path:
        """Published document snapshots, one directory per snapshot id."""
        return self.artifacts_root / DOCUMENTS_DATASET / SNAPSHOTS_DIR

    @property
    def document_transient_root(self) -> Path:
        """Run-scoped staging for the document-storage pipeline."""
        return self.artifacts_root / TRANSIENT_DIR / DOCUMENTS_DATASET

    @property
    def fixtures_root(self) -> Path:
        """Committed raw-payload fixtures, one directory per fixture id."""
        return self.artifacts_root / FIXTURES_DIR

    def run_dir(self, run_id: str) -> Path:
        """Return the staging directory for one document-storage run."""
        return self.document_transient_root / RUNS_DIR / run_id

    def run_checkpoints_dir(self, run_id: str) -> Path:
        """Return the resumable-checkpoint directory for one run."""
        return self.run_dir(run_id) / CHECKPOINTS_DIR

    def run_chunks_dir(self, run_id: str) -> Path:
        """Return the worker chunk directory for one run."""
        return self.run_dir(run_id) / "chunks"

    def snapshot_dir(self, snapshot_id: str) -> Path:
        """Return the directory for one published document snapshot."""
        return self.documents_root / snapshot_id

    def fixture_dir(self, fixture_id: str) -> Path:
        """Return the directory for one raw-payload fixture."""
        return self.fixtures_root / fixture_id

    def fixture_db_path(self, fixture_id: str) -> Path:
        """Return the SQLite path holding one fixture's raw payloads."""
        return self.fixture_dir(fixture_id) / PAYLOAD_DB_NAME

    def fixture_manifest_path(self, fixture_id: str) -> Path:
        """Return the lineage manifest for one fixture."""
        return self.fixture_dir(fixture_id) / FIXTURE_MANIFEST_NAME

    @property
    def review_runs_root(self) -> Path:
        """Durable root of generated review runs, one directory per run id.

        A review run is a deliverable meant to be diffed against a later one, so it
                must outlive its command and must not sit where staging may be reclaimed.
        """
        return self.artifacts_root / DOCUMENTS_DATASET / REVIEW_RUNS_DIR

    def review_run_dir(self, run_id: str) -> Path:
        """Return the directory one review run's artifacts are written into."""
        return self.review_runs_root / run_id


# edgar_sec/, i.e. three levels up from this file (foundation/runtime/paths.py).
PACKAGE_ROOT = Path(__file__).resolve().parents[2]


class ProjectRootError(RuntimeError):
    """The working directory is inside the package, not the project root."""


def _reject_package_working_directory(root: Path) -> None:
    """Fail loudly when the CWD is inside the ``edgar_sec`` package.

    ``resolve_paths`` treats the CWD as the project root, so running from ``edgar_sec/``
    quietly derives a second artifacts tree no reader consults; ``repo_root`` skips this.
    """
    resolved = root.resolve()
    if resolved == PACKAGE_ROOT or PACKAGE_ROOT in resolved.parents:
        raise ProjectRootError(
            f"the working directory is inside the edgar_sec package ({resolved}). "
            "Run from the project root, so .artifacts/, uploads/, and cache/ "
            "resolve beside the package rather than inside it."
        )


def _resolve_artifacts_root(root: Path) -> Path:
    """Resolve the registered artifacts root against the project root.

    A relative value (the default) is anchored beside the package; an absolute
            one is taken as given, which is how a test redirects the workspace.
    """
    configured = Path(str(resolve_settings()["artifacts.root"]))
    if configured.is_absolute():
        return configured
    return (root / configured).resolve()


def resolve_paths(repo_root: Path | str | None = None) -> ProjectPaths:
    """Resolve standard project layout from the current working directory.

    The CWD *is* the project root, so the CLI must run from the repository root.
    ``artifacts.root`` is the single authority for the artifacts root.
    """
    if repo_root is not None:
        root = Path(repo_root)
    else:
        root = Path.cwd()
        _reject_package_working_directory(root)

    artifacts_root = _resolve_artifacts_root(root)

    uploads_root = root / "uploads"

    return ProjectPaths(
        repo_root=root,
        artifacts_root=artifacts_root,
        uploads_root=uploads_root,
    )


__all__ = [
    "CHECKPOINTS_DIR",
    "CURRENT_DIR",
    "DOCUMENTS_DATASET",
    "FIXTURES_DIR",
    "FIXTURE_MANIFEST_NAME",
    "PACKAGE_ROOT",
    "PAYLOAD_DB_NAME",
    "PLANS_DIR",
    "PLAN_FILE_NAME",
    "POINTER_FILE_NAME",
    "REVIEW_RUNS_DIR",
    "RUNS_DIR",
    "SNAPSHOTS_DIR",
    "TRANSIENT_DIR",
    "ProjectPaths",
    "ProjectRootError",
    "current_pointer_path",
    "plan_dir",
    "resolve_paths",
    "transient_dir",
]
