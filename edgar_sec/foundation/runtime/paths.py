"""Root directory layout resolution for edgar_sec."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .env import get_env

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
    cache_root: Path
    uploads_root: Path

    def ensure_directories(self) -> None:
        """Create standard runtime directories if they do not exist."""
        self.artifacts_root.mkdir(parents=True, exist_ok=True)
        self.cache_root.mkdir(parents=True, exist_ok=True)
        self.uploads_root.mkdir(parents=True, exist_ok=True)


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


def resolve_paths(repo_root: Path | str | None = None) -> ProjectPaths:
    """Resolve standard project layout from environment or current working directory.

    With no ``repo_root``, the current working directory *is* the project root.
    Run the CLI from the repository root: the artifacts, uploads, and cache
    roots are all derived from it, and running from anywhere else silently
    publishes into a parallel tree.
    """
    if repo_root is not None:
        root = Path(repo_root)
    else:
        root = Path.cwd()
        _reject_package_working_directory(root)

    artifacts_override = get_env("EDGAR_ARTIFACTS_DIR", default="")
    artifacts_root = (
        Path(artifacts_override).resolve()
        if artifacts_override
        else root / ".artifacts"
    )

    cache_override = get_env("EDGAR_CACHE_DIR", default="")
    cache_root = (
        Path(cache_override).resolve() if cache_override else artifacts_root / "cache"
    )

    uploads_root = root / "uploads"

    return ProjectPaths(
        repo_root=root,
        artifacts_root=artifacts_root,
        cache_root=cache_root,
        uploads_root=uploads_root,
    )


__all__ = [
    "CURRENT_DIR",
    "PACKAGE_ROOT",
    "PLANS_DIR",
    "PLAN_FILE_NAME",
    "POINTER_FILE_NAME",
    "SNAPSHOTS_DIR",
    "TRANSIENT_DIR",
    "ProjectPaths",
    "ProjectRootError",
    "current_pointer_path",
    "plan_dir",
    "resolve_paths",
    "transient_dir",
]
