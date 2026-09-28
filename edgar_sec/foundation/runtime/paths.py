"""Root directory layout resolution for edgar_sec."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .env import get_env


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


def resolve_paths(repo_root: Path | str | None = None) -> ProjectPaths:
    """Resolve standard project layout from environment or current working directory."""
    root = Path(repo_root) if repo_root is not None else Path.cwd()

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


__all__ = ["ProjectPaths", "resolve_paths"]
