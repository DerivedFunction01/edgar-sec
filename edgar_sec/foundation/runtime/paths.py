"""Root directory layout resolution for edgar_sec."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .settings import resolve_settings
from .settings.paths import DEFAULT_DISTRIBUTION_ROOT

# Cross-pipeline artifact layout: an immutable dataset under a dataset root, a
# tip naming what is published, and resumable work under a transient root.
TRANSIENT_DIR = "transient"
CURRENT_DIR = "current"
PLAN_FILE_NAME = "plan.json"
SNAPSHOTS_DIR = "snapshots"
RUNTIME_DIR = "runtime"
DATA_FILE_NAME = "data.parquet"
PARQUET_PART_GLOB = "part-*.parquet"


def transient_dir(artifacts_root: Path, dataset: str, run_id: str) -> Path:
    """Return the staging directory for one resumable run of a dataset."""
    return artifacts_root / TRANSIENT_DIR / dataset / run_id


def runtime_root(artifacts_root: Path | str) -> Path:
    return Path(artifacts_root) / RUNTIME_DIR


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
        return runtime_root(self.artifacts_root)

    @property
    def distribution_root(self) -> Path:
        return distribution_root(self.repo_root)


def distribution_root(repo_root: Path | str | None = None) -> Path:
    """Resolve the registered distribution root."""
    configured = Path(
        str(resolve_settings().get("distribution.root", DEFAULT_DISTRIBUTION_ROOT))
    )
    if configured.is_absolute():
        return configured
    base = Path(repo_root) if repo_root is not None else Path.cwd()
    return (base / configured).resolve()


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
    "CURRENT_DIR",
    "PACKAGE_ROOT",
    "PLAN_FILE_NAME",
    "RUNTIME_DIR",
    "SNAPSHOTS_DIR",
    "TRANSIENT_DIR",
    "ProjectPaths",
    "ProjectRootError",
    "distribution_root",
    "resolve_paths",
    "runtime_root",
    "transient_dir",
]
