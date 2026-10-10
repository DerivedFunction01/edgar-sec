"""Root directory layout resolution for edgar_sec."""

from __future__ import annotations

import re
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

# Universal pipeline constants used across layers.
PLANS_DIR = "plans"
CHUNKS_DIR = "chunks"
RUNS_DIR = "runs"
RUN_LOCK_FILE = "run.lock"
RUN_MANIFEST_FILE = "run_manifest.json"
PUBLICATION_LOCK_FILE = ".publication.lock"
_PATH_COMPONENT_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")


def validate_path_component(value: str, label: str) -> str:
    if not isinstance(value, str) or not _PATH_COMPONENT_RE.fullmatch(value):
        raise ValueError(f"invalid {label}: {value!r}")
    return value


def validate_safe_id(
    value: str,
    label: str = "identifier",
    min_len: int = 1,
    max_len: int | None = None,
) -> str:
    """Validate a path identifier against its configured length bounds."""
    if not value or value in (".", ".."):
        raise ValueError(f"invalid {label}: {value!r}")
    if len(value) < min_len:
        raise ValueError(f"{label} too short: {value!r}")
    if max_len is not None and len(value) > max_len:
        raise ValueError(f"{label} too long: {value!r}")
    for char in value:
        if not (char.isalnum() or char in "_.-"):
            raise ValueError(f"invalid {label}: {value!r}")
    return value


def transient_dir(artifacts_root: Path, dataset: str, run_id: str) -> Path:
    """Return the staging directory for one resumable run of a dataset."""
    return transient_dataset_root(artifacts_root, dataset) / run_id


def dataset_root(artifacts_root: Path | str, dataset: str) -> Path:
    """Return the validated root for one artifacts dataset."""
    return Path(artifacts_root) / validate_path_component(dataset, "dataset")


def transient_dataset_root(artifacts_root: Path | str, dataset: str) -> Path:
    """Return the transient root for one artifacts dataset."""
    return (
        Path(artifacts_root)
        / TRANSIENT_DIR
        / validate_path_component(dataset, "dataset")
    )


def snapshots_root(artifacts_root: Path | str, dataset: str) -> Path:
    """Return the published snapshots root for one artifacts dataset."""
    return dataset_root(artifacts_root, dataset) / SNAPSHOTS_DIR


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
            f"Run from the project root, so files and directories "
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
    "CASES_DIR",
    "CHUNKS_DIR",
    "CURRENT_DIR",
    "DATA_FILE_NAME",
    "PACKAGE_ROOT",
    "PLAN_FILE_NAME",
    "PLANS_DIR",
    "PUBLICATION_LOCK_FILE",
    "PARQUET_PART_GLOB",
    "RUN_LOCK_FILE",
    "RUN_MANIFEST_FILE",
    "RUNS_DIR",
    "RUNTIME_DIR",
    "SNAPSHOTS_DIR",
    "TRANSIENT_DIR",
    "ProjectPaths",
    "ProjectRootError",
    "dataset_root",
    "distribution_root",
    "resolve_paths",
    "runtime_root",
    "snapshots_root",
    "transient_dataset_root",
    "transient_dir",
    "validate_path_component",
    "validate_safe_id",
]
