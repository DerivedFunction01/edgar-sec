"""Side-effect-free, environment-aware artifact path layout."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


def _safe_id(value: str, label: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID.fullmatch(value):
        raise ValueError(
            f"{label} must contain only letters, numbers, '.', '_', or '-'"
        )
    return value


def _path(value: str | os.PathLike[str]) -> Path:
    return Path(value).expanduser()


@dataclass(frozen=True)
class ProjectPaths:
    """Project-wide roots resolved without touching the filesystem."""

    artifacts_root: Path
    config_path: Path
    cache_root: Path

    def phase(self, phase: str) -> "PhasePaths":
        return PhasePaths(self, _safe_id(phase, "phase"))

    @property
    def test_runs_root(self) -> Path:
        return self.artifacts_root / "test-runs"

    @property
    def acceptance_root(self) -> Path:
        return self.artifacts_root / "acceptance"

    def canonical_output(self, phase: str, dataset: str, storage_format: str) -> Path:
        """Return the canonical output path for a logical dataset."""
        phase = _safe_id(phase, "phase")
        dataset = _safe_id(dataset, "dataset")
        extension = {"parquet": "parquet", "jsonl": "jsonl", "sqlite": "sqlite"}.get(
            storage_format
        )
        if extension is None:
            raise ValueError(f"unsupported storage format: {storage_format}")
        return self.artifacts_root / phase / "canonical" / f"{dataset}.{extension}"


@dataclass(frozen=True)
class PhasePaths:
    project: ProjectPaths
    phase: str

    @property
    def phase_root(self) -> Path:
        return self.project.artifacts_root / self.phase

    @property
    def runs_root(self) -> Path:
        return self.phase_root / "runs"

    @property
    def preview_root(self) -> Path:
        return self.phase_root / "preview"

    def run(self, run_id: str) -> "RunPaths":
        return RunPaths(self, _safe_id(run_id, "run_id"))


@dataclass(frozen=True)
class RunPaths:
    phase_paths: PhasePaths
    run_id: str

    @property
    def run_root(self) -> Path:
        return self.phase_paths.runs_root / self.run_id

    @property
    def plan_path(self) -> Path:
        return self.run_root / "plan.json"

    @property
    def partitions_root(self) -> Path:
        return self.run_root / "partitions"

    @property
    def workers_root(self) -> Path:
        return self.run_root / "workers"

    def partition_manifest(self, partition_id: int) -> Path:
        return self.partitions_root / f"partition-{_partition_id(partition_id)}.json"

    def partition_root(self, partition_id: int) -> Path:
        return self.partitions_root / f"partition-{_partition_id(partition_id)}"

    def partition_chunks(self, partition_id: int) -> Path:
        return self.partition_root(partition_id) / "chunks"

    def worker_root(self, worker_id: str, attempt_id: str) -> Path:
        return (
            self.workers_root
            / _safe_id(worker_id, "worker_id")
            / _safe_id(attempt_id, "attempt_id")
        )

    def ensure_run_layout(self) -> None:
        self.partitions_root.mkdir(parents=True, exist_ok=True)
        self.workers_root.mkdir(parents=True, exist_ok=True)

    def ensure_worker_layout(self, worker_id: str, attempt_id: str) -> Path:
        path = self.worker_root(worker_id, attempt_id)
        path.mkdir(parents=True, exist_ok=True)
        return path


def _partition_id(value: int) -> str:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError("partition_id must be a positive integer")
    return f"{value:05d}"


def resolve_paths(
    phase: str | None = None,
    run_id: str | None = None,
    env: Mapping[str, str] | None = None,
) -> ProjectPaths | PhasePaths | RunPaths:
    """Resolve shared paths from environment, without creating directories.

    ``EDGAR_ARTIFACTS_ROOT`` controls the shared generated-artifact workspace.
    ``EDGAR_CONFIG_PATH`` and ``EDGAR_CACHE_ROOT`` override their derived
    locations. Supplying only ``phase`` or both ``phase`` and ``run_id``
    returns the corresponding narrower layout object.
    """
    values = os.environ if env is None else env
    artifacts_root = _path(values.get("EDGAR_ARTIFACTS_ROOT", ".artifacts"))
    config_path = _path(
        values.get("EDGAR_CONFIG_PATH", artifacts_root / "metadata" / "config.json")
    )
    cache_root = _path(values.get("EDGAR_CACHE_ROOT", artifacts_root / "caches"))
    project = ProjectPaths(artifacts_root, config_path, cache_root)
    if phase is None:
        if run_id is not None:
            raise ValueError("phase is required when run_id is supplied")
        return project
    phase_paths = project.phase(phase)
    if run_id is None:
        return phase_paths
    return phase_paths.run(run_id)


__all__ = ["PhasePaths", "ProjectPaths", "RunPaths", "resolve_paths"]
