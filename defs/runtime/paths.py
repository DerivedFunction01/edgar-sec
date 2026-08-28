"""Side-effect-free, environment-aware artifact path layout."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path, PurePosixPath

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_PARTITION_DIR = re.compile(r"^partition-(\d{5,})$")
_PARTITION_MANIFEST = re.compile(r"^partition-(\d{5,})\.json$")

MERGE_DIR_NAME = "merge"
MERGE_REPORT_NAME = "merge_report.json"


class ArtifactRole(str, Enum):
    """Recognized roles an artifact path can play under the artifacts root."""

    RUN_PLAN = "run_plan"
    PARTITION_MANIFEST = "partition_manifest"
    PARTITION_CHUNK = "partition_chunk"
    CHUNK = "chunk"
    PREVIEW = "preview"
    CANONICAL = "canonical"
    MERGE_REPORT = "merge_report"
    PARTITION_ARTIFACT = "partition_artifact"
    WORKER_FRAGMENT = "worker_fragment"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ArtifactClassification:
    """Result of classifying one artifact path relative to the artifacts root."""

    relative_path: str
    role: ArtifactRole
    phase: str | None = None
    run_id: str | None = None
    partition_id: int | None = None


def merge_report_path_in(run_root: str | os.PathLike[str]) -> Path:
    """Merge report path for a run directory supplied as a plain path."""
    return Path(run_root) / MERGE_DIR_NAME / MERGE_REPORT_NAME


def partition_merge_root_in(
    run_root: str | os.PathLike[str], partition_id: int
) -> Path:
    return (
        Path(run_root)
        / "partitions"
        / f"partition-{_partition_id(partition_id)}"
        / MERGE_DIR_NAME
    )


def partition_artifact_path_in(
    run_root: str | os.PathLike[str], partition_id: int, filename: str
) -> Path:
    if not filename or Path(filename).name != filename:
        raise ValueError("partition artifact filename must be a basename")
    return partition_merge_root_in(run_root, partition_id) / filename


def partition_merge_report_path_in(
    run_root: str | os.PathLike[str], partition_id: int
) -> Path:
    return partition_merge_root_in(run_root, partition_id) / MERGE_REPORT_NAME


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

    def phase(self, phase: str) -> PhasePaths:
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

    def run(self, run_id: str) -> RunPaths:
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

    @property
    def merge_root(self) -> Path:
        return self.run_root / MERGE_DIR_NAME

    @property
    def merge_report_path(self) -> Path:
        return self.merge_root / MERGE_REPORT_NAME

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


def classify_artifact_path(path: str | os.PathLike[str]) -> ArtifactClassification:
    """Classify an artifact path relative to the artifacts root.

    This is the read-side mirror of the path builders above: every path
    produced by ``RunPaths``/``PhasePaths`` classifies back to the same role
    and partition id. Paths outside the recognized layout classify as
    ``UNKNOWN``; when they still sit inside a recognized ``<phase>/runs/
    <run_id>/`` subtree, the phase and run id are preserved so consumers can
    attribute the file. Absolute paths are rejected.
    """
    pure = PurePosixPath(Path(path).as_posix())
    if pure.is_absolute() or (len(pure.parts) > 0 and pure.parts[0] == "/"):
        raise ValueError("artifact path must be relative to the artifacts root")
    parts = pure.parts
    base = ArtifactClassification(
        relative_path=pure.as_posix(), role=ArtifactRole.UNKNOWN
    )
    if len(parts) < 2:
        return base
    phase, second = parts[0], parts[1]
    if not _SAFE_ID.fullmatch(phase):
        return base
    if second == "runs":
        if len(parts) < 3:
            return base
        run_id = parts[2]
        if not _SAFE_ID.fullmatch(run_id):
            return base
        rest = parts[3:]

        def with_run(
            role: ArtifactRole, partition_id: int | None = None
        ) -> ArtifactClassification:
            return ArtifactClassification(
                relative_path=pure.as_posix(),
                role=role,
                phase=phase,
                run_id=run_id,
                partition_id=partition_id,
            )

        def run_unknown() -> ArtifactClassification:
            """Unrecognized file inside a known run: keep its attribution."""
            return with_run(ArtifactRole.UNKNOWN)

        if rest == ("plan.json",):
            return with_run(ArtifactRole.RUN_PLAN)
        if rest == (MERGE_DIR_NAME, MERGE_REPORT_NAME):
            return with_run(ArtifactRole.MERGE_REPORT)
        if len(rest) == 2 and rest[0] == "chunks":
            return with_run(ArtifactRole.CHUNK)
        if len(rest) >= 1 and rest[0] == "partitions":
            if len(rest) == 2:
                match = _PARTITION_MANIFEST.fullmatch(rest[1])
                if match is None:
                    return run_unknown()
                return with_run(ArtifactRole.PARTITION_MANIFEST, int(match.group(1)))
            match = _PARTITION_DIR.fullmatch(rest[1]) if len(rest) >= 2 else None
            if match is None:
                return run_unknown()
            partition_id = int(match.group(1))
            if len(rest) == 4 and rest[2] == "chunks":
                return with_run(ArtifactRole.PARTITION_CHUNK, partition_id)
            if len(rest) == 4 and rest[2] == MERGE_DIR_NAME:
                return with_run(ArtifactRole.PARTITION_ARTIFACT, partition_id)
            return run_unknown()
        if len(rest) >= 3 and rest[0] == "workers":
            return with_run(ArtifactRole.WORKER_FRAGMENT)
        return run_unknown()
    if second == "preview":
        if len(parts) < 3 or not _SAFE_ID.fullmatch(parts[2]):
            return base
        return ArtifactClassification(
            relative_path=pure.as_posix(),
            role=ArtifactRole.PREVIEW,
            phase=phase,
            run_id=parts[2],
        )
    if second == "canonical":
        return ArtifactClassification(
            relative_path=pure.as_posix(),
            role=ArtifactRole.CANONICAL,
            phase=phase,
        )
    return base


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


__all__ = [
    "MERGE_DIR_NAME",
    "MERGE_REPORT_NAME",
    "ArtifactClassification",
    "ArtifactRole",
    "PhasePaths",
    "ProjectPaths",
    "RunPaths",
    "classify_artifact_path",
    "merge_report_path_in",
    "partition_artifact_path_in",
    "partition_merge_report_path_in",
    "partition_merge_root_in",
    "resolve_paths",
]
