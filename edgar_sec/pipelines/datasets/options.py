"""The one typed options model shared by the datasets CLI and operator."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .paths import DatasetsPaths, resolve_datasets_paths


@dataclass(frozen=True, slots=True)
class DatasetsOptions:
    """Everything one datasets command invocation needs."""

    artifacts_root: Path | None = None
    branch: str = "main"

    def datasets_paths(self) -> DatasetsPaths:
        """Datasets layout this invocation reads or writes."""
        return resolve_datasets_paths(self.artifacts_root)


def datasets_options(
    *,
    artifacts_root: str | Path | None = None,
    branch: str = "main",
) -> DatasetsOptions:
    """Build datasets options from raw values."""
    return DatasetsOptions(
        artifacts_root=(Path(artifacts_root).resolve() if artifacts_root else None),
        branch=branch or "main",
    )


__all__ = ["DatasetsOptions", "datasets_options"]
