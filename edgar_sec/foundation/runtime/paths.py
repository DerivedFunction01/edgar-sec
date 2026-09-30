"""Root directory layout resolution for edgar_sec."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .settings import resolve_settings

# Shared artifact-layout convention. Every pipeline publishes an immutable
# dataset under a dataset root and records the "currently published" identity in
# a pointer file; resumable work lives under a transient root. These names are
# the cross-pipeline contract, so they are declared once here rather than being
# restated in each pipeline's paths module, where a rename in one place would
# silently desynchronize the others.
TRANSIENT_DIR = "transient"
CURRENT_DIR = "current"
POINTER_FILE_NAME = "pointer.json"
PLAN_FILE_NAME = "plan.json"
SNAPSHOTS_DIR = "snapshots"
PLANS_DIR = "plans"

# Document-storage layout. Kept beside the shared names above because the
# snapshot root, the pointer that names the published snapshot, and the
# transient run root are the *same* cross-pipeline contract the generic
# constants encode; only the dataset name differs.
DOCUMENTS_DATASET = "document_storage"
RUNS_DIR = "runs"
CHECKPOINTS_DIR = "checkpoints"
FIXTURES_DIR = "fixtures"
PAYLOAD_DB_NAME = "payloads.sqlite"
FIXTURE_MANIFEST_NAME = "fixture_manifest.json"


def current_pointer_path(snapshots_root: Path) -> Path:
    """Return the pointer file naming the currently published snapshot.

    Shared so every dataset resolves "current" identically; a pipeline that
    invented its own shape would make ``status`` ambiguous across datasets.
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
        """Create standard runtime directories if they do not exist."""
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
    #
    # The document-storage pipeline is the one consumer of a *fixture root*:
    # the raw-payload store that makes the offline fetch path work, and the
    # review bundles the review tool renders. Both outlive a single run, so
    # neither belongs under the run-scoped transient tree.

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
        return self.artifacts_root / DOCUMENTS_DATASET / FIXTURES_DIR

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

    def review_dir(self, run_id: str) -> Path:
        """Return the directory review bundles are rendered into."""
        return self.run_dir(run_id) / "review"


# edgar_sec/, i.e. three levels up from this file (foundation/runtime/paths.py).
PACKAGE_ROOT = Path(__file__).resolve().parents[2]


class ProjectRootError(RuntimeError):
    """The working directory is inside the package, not the project root."""


def _reject_package_working_directory(root: Path) -> None:
    """Fail loudly when the CWD is inside the ``edgar_sec`` package.

    ``resolve_paths`` treats the working directory as the project root, so
    running from ``edgar_sec/`` does not fail -- it quietly derives a *second*
    artifacts tree at ``edgar_sec/.artifacts``, with ``uploads/`` and ``cache/``
    alongside it. Every later command then reports an empty catalog, and a
    full-corpus run publishes real work into a tree nothing reads.

    This is worth a hard error rather than a heuristic search for the "real"
    root: the package source directory is never a legitimate project root, so
    the check is unambiguous even though recovering the intended root is not.
    An explicit ``repo_root`` argument is accepted, because a caller that names
    the root has already answered the question.
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

    The setting defaults to a relative ``.artifacts``, which is anchored here so
    it lands beside the package. An absolute value is taken as given, which is
    how a test or a side-by-side tree redirects the whole workspace.
    """
    configured = Path(str(resolve_settings()["artifacts.root"]))
    if configured.is_absolute():
        return configured
    return (root / configured).resolve()


def resolve_paths(repo_root: Path | str | None = None) -> ProjectPaths:
    """Resolve standard project layout from environment or current working directory.

    With no ``repo_root``, the current working directory *is* the project root.
    Run the CLI from the repository root: the artifacts, uploads, and cache
    roots are all derived from it, and running from anywhere else silently
    publishes into a parallel tree.

    The artifacts root is read from the registered ``artifacts.root`` setting, so
    there is one authority for it. It used to be read here from a private
    ``EDGAR_ARTIFACTS_DIR``, which meant two settings answered the same question
    and ignored each other: setting ``ARTIFACTS_ROOT`` changed what the registry
    reported while the resolver kept using ``.artifacts``, and setting
    ``EDGAR_ARTIFACTS_DIR`` did the reverse. A relative value is anchored to the
    project root so the default stays beside the package rather than wherever
    the process happens to be.
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
