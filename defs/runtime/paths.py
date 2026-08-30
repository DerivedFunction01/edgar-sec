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
    PREVIEW = "preview"
    PUBLISHED_DATASET = "published_dataset"
    PUBLISHED_MANIFEST = "published_manifest"
    MERGE_REPORT = "merge_report"
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
        / MERGE_DIR_NAME
        / "partitions"
        / f"partition-{_partition_id(partition_id)}"
    )


def partition_merge_report_path_in(
    run_root: str | os.PathLike[str], partition_id: int
) -> Path:
    return (
        Path(run_root)
        / MERGE_DIR_NAME
        / "partitions"
        / (f"partition-{_partition_id(partition_id)}.json")
    )


def _safe_id(value: str, label: str) -> str:
    if not isinstance(value, str) or not _SAFE_ID.fullmatch(value):
        raise ValueError(
            f"{label} must contain only letters, numbers, '.', '_', or '-'"
        )
    return value


def _path(value: str | os.PathLike[str]) -> Path:
    return Path(value).expanduser()


@dataclass(frozen=True)
class FixturePaths:
    """Typed layout for an immutable raw/fixture directory."""

    root: Path
    fixture_id: str
    dialect: str = "duckdb"

    @property
    def manifest_path(self) -> Path:
        return self.root / "fixture.manifest.json"

    @property
    def db_path(self) -> Path:
        ext = {"duckdb": "duckdb", "sqlite": "sqlite", "sqlite3": "sqlite"}.get(
            self.dialect.lower(), self.dialect.lower()
        )
        return self.root / f"fixture.{ext}"

    def ensure_layout(self) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        return self.root


@dataclass(frozen=True)
class ProjectPaths:
    """Project-wide roots resolved without touching the filesystem."""

    artifacts_root: Path
    cache_root: Path

    def phase(self, phase: str) -> PhasePaths:
        return PhasePaths(self, _safe_id(phase, "phase"))

    @property
    def runtime_root(self) -> Path:
        return self.artifacts_root / "runtime"

    @property
    def runtime_config_path(self) -> Path:
        return self.runtime_root / "config.json"

    @property
    def test_runs_root(self) -> Path:
        return self.artifacts_root / "test-runs"

    def test_run_root(self, scope: str, suite: str, run_id: str) -> Path:
        """Return a generated test-report directory without creating it."""
        return (
            self.test_runs_root
            / _safe_id(scope, "test scope")
            / _safe_id(suite, "test suite")
            / _safe_id(run_id, "test run id")
        )

    @property
    def acceptance_root(self) -> Path:
        return self.artifacts_root / "acceptance"

    @property
    def fixtures_root(self) -> Path:
        return self.artifacts_root / "fixtures"

    def fixture(self, fixture_id: str, dialect: str = "duckdb") -> FixturePaths:
        safe = _safe_id(fixture_id, "fixture_id")
        return FixturePaths(self.fixtures_root / safe, safe, dialect=dialect)

    @property
    def manifests_root(self) -> Path:
        return self.artifacts_root / "manifests"

    @property
    def transient_root(self) -> Path:
        return self.artifacts_root / "transient"

    def dataset_manifests(self, phase: str, dataset: str, partition: str = "") -> Path:
        """Directory containing immutable manifests for a dataset."""
        phase_safe = _safe_id(phase, "phase")
        dataset_safe = _safe_id(dataset, "dataset")
        scope_dir = (
            f"partitions/{partition}" if partition and partition != "final" else "final"
        )
        return self.manifests_root / phase_safe / dataset_safe / scope_dir

    def manifest_path_for(
        self, phase: str, dataset: str, artifact_id_value: str, partition: str = ""
    ) -> Path:
        """Path to an immutable manifest for an artifact."""
        safe_id = _safe_id(artifact_id_value, "artifact_id")
        return self.dataset_manifests(phase, dataset, partition) / f"{safe_id}.json"

    def published_dataset_path(
        self, phase: str, dataset: str, storage_format: str, partition: str = ""
    ) -> Path:
        """Return the published dataset path inside the manifests hierarchy."""
        phase_safe = _safe_id(phase, "phase")
        dataset_safe = _safe_id(dataset, "dataset")
        extension = {"parquet": "parquet", "jsonl": "jsonl", "sqlite": "sqlite"}.get(
            storage_format
        )
        if extension is None:
            raise ValueError(f"unsupported storage format: {storage_format}")
        return (
            self.dataset_manifests(phase_safe, dataset_safe, partition)
            / f"{dataset_safe}.{extension}"
        )

    def published_partition_dataset_path(
        self, phase: str, dataset: str, partition: int | str, storage_format: str
    ) -> Path:
        phase_safe = _safe_id(phase, "phase")
        dataset_safe = _safe_id(dataset, "dataset")
        partition_safe = _safe_id(
            f"partition-{partition:05d}"
            if isinstance(partition, int)
            else str(partition),
            "partition",
        )
        extension = {"parquet": "parquet", "jsonl": "jsonl"}.get(storage_format)
        if extension is None:
            raise ValueError(f"unsupported storage format: {storage_format}")
        return (
            self.manifests_root
            / phase_safe
            / dataset_safe
            / "partitions"
            / partition_safe
            / f"{dataset_safe}.{extension}"
        )


@dataclass(frozen=True)
class PhasePaths:
    project: ProjectPaths
    phase: str

    @property
    def phase_root(self) -> Path:
        return self.project.artifacts_root / self.phase

    @property
    def config_path(self) -> Path:
        return self.phase_root / "config.json"

    @property
    def runs_root(self) -> Path:
        return self.project.transient_root / self.phase / "runs"

    @property
    def preview_root(self) -> Path:
        return self.project.transient_root / self.phase / "preview"

    @property
    def catalogs_root(self) -> Path:
        return self.project.transient_root / self.phase / "catalogs"

    def published_dataset(
        self, dataset: str, storage_format: str, partition: str = ""
    ) -> Path:
        return self.project.published_dataset_path(
            self.phase, dataset, storage_format, partition
        )

    def fixture(self, fixture_id: str, dialect: str = "duckdb") -> FixturePaths:
        safe = _safe_id(fixture_id, "fixture_id")
        return FixturePaths(
            self.project.acceptance_root / self.phase / "fixtures" / safe,
            safe,
            dialect=dialect,
        )

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

    def worker_chunk_db(self, worker_id: str, attempt_id: str, chunk_id: str) -> Path:
        """Private transient chunk database file for one worker attempt."""
        safe_chunk = _safe_id(chunk_id, "chunk_id")
        return self.worker_root(worker_id, attempt_id) / f"{safe_chunk}.db"

    def worker_chunk_glob(self) -> Path:
        """Glob pattern matching all transient worker chunk databases."""
        return self.workers_root / "*" / "*" / "chunk-*.db"

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
    if parts[0] == "transient":
        if len(parts) < 3:
            return base
        phase, second = parts[1], parts[2]
        if not _SAFE_ID.fullmatch(phase):
            return base
        if second == "runs":
            if len(parts) < 4:
                return base
            run_id = parts[3]
            if not _SAFE_ID.fullmatch(run_id):
                return base
            rest = parts[4:]

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
                return with_run(ArtifactRole.UNKNOWN)

            if rest == ("plan.json",):
                return with_run(ArtifactRole.RUN_PLAN)
            if rest == (MERGE_DIR_NAME, MERGE_REPORT_NAME):
                return with_run(ArtifactRole.MERGE_REPORT)
            if (
                len(rest) == 3
                and rest[0] == MERGE_DIR_NAME
                and rest[1] == "partitions"
                and _PARTITION_MANIFEST.fullmatch(rest[2])
                and rest[2].endswith(".json")
            ):
                match = _PARTITION_MANIFEST.fullmatch(rest[2])
                return with_run(ArtifactRole.MERGE_REPORT, int(match.group(1)))
            if len(rest) == 2 and rest[0] == "partitions":
                match = _PARTITION_MANIFEST.fullmatch(rest[1])
                if match is None:
                    return run_unknown()
                return with_run(ArtifactRole.PARTITION_MANIFEST, int(match.group(1)))
            if len(rest) == 4 and rest[0] == "partitions":
                match = _PARTITION_DIR.fullmatch(rest[1])
                if match is None:
                    return run_unknown()
                partition_id = int(match.group(1))
                if rest[2] == "chunks":
                    return with_run(ArtifactRole.PARTITION_CHUNK, partition_id)
            if len(rest) >= 3 and rest[0] == "workers":
                return with_run(ArtifactRole.WORKER_FRAGMENT)
            return run_unknown()
        if second == "preview":
            if len(parts) < 4 or not _SAFE_ID.fullmatch(parts[3]):
                return base
            return ArtifactClassification(
                relative_path=pure.as_posix(),
                role=ArtifactRole.PREVIEW,
                phase=phase,
            )
        return base
    if parts[0] == "manifests" and len(parts) >= 5:
        prod_phase = parts[1]
        scope = parts[3]
        filename = parts[-1]
        is_manifest = filename.endswith(".json")
        role = (
            ArtifactRole.PUBLISHED_MANIFEST
            if is_manifest
            else ArtifactRole.PUBLISHED_DATASET
        )
        part_id = None
        if scope == "partitions" and len(parts) >= 6:
            m = _PARTITION_DIR.fullmatch(parts[4])
            if m:
                part_id = int(m.group(1))
        return ArtifactClassification(
            relative_path=pure.as_posix(),
            role=role,
            phase=prod_phase,
            partition_id=part_id,
        )
    return base


def resolve_paths(
    phase: str | None = None,
    run_id: str | None = None,
    env: Mapping[str, str] | None = None,
) -> ProjectPaths | PhasePaths | RunPaths:
    """Resolve shared paths from the settings registry, without directories.

    ``artifacts.root`` (environment name ``ARTIFACTS_ROOT``) controls the
    shared generated-artifact workspace; ``CACHE_ROOT`` overrides the derived
    cache location. Values resolve through the shared environment layer (direct
    environment, then the canonical ``.env`` file). Supplying an explicit ``env``
    mapping bypasses that resolution entirely. Supplying only ``phase`` or both
    ``phase`` and ``run_id`` returns the corresponding narrower layout object.
    """
    if env is None:
        from .settings import resolve_settings

        values = resolve_settings(include=["artifacts", "cache"])
        artifacts_root = _path(values["artifacts.root"])
        cache_root = _path(values["cache.root"])
    else:
        artifacts_root = _path(env.get("ARTIFACTS_ROOT", ".artifacts"))
        cache_root = _path(env.get("CACHE_ROOT", artifacts_root / "caches"))
    project = ProjectPaths(artifacts_root, cache_root)
    if phase is None:
        if run_id is not None:
            raise ValueError("phase is required when run_id is supplied")
        return project
    phase_paths = project.phase(phase)
    if run_id is None:
        return phase_paths
    return phase_paths.run(run_id)


_ARTIFACT_LITERAL_CANDIDATE_RE = r"\.artifacts"
_ARTIFACT_LITERAL_RE = re.compile(
    r"""(?:["']\.artifacts[/\\]|Path\(\s*["']\.artifacts["']\s*\))"""
)

_ARTIFACT_ALLOWED_PREFIXES = (
    "defs/runtime/paths.py",
    "defs/runtime/settings/paths.py",
    "defs/tests/",
    "check.py",
    "init_venv.py",
    "scratch/",
)


def _is_artifact_path_allowed(path: str) -> bool:
    normalized = path.replace(os.sep, "/")
    if any(
        normalized == prefix or normalized.startswith(prefix)
        for prefix in _ARTIFACT_ALLOWED_PREFIXES
    ):
        return True
    from .scanners.engine import is_test_file

    return is_test_file(path)


def _match_artifact_line(path: str, line_number: int, text: str, source: str) -> list:
    if _is_artifact_path_allowed(path):
        return []
    from .checks import ScannerFinding

    findings: list[ScannerFinding] = []
    if _ARTIFACT_LITERAL_RE.search(text):
        findings.append(
            ScannerFinding(
                scanner="artifact-paths",
                source=source,
                path=path,
                line=line_number,
                message="hardcoded .artifacts path literal in source code",
                hint="resolve paths dynamically through defs.runtime.paths.resolve_paths() instead",
            )
        )
    return findings


def scan_artifact_path_literals(
    repo_root: str | os.PathLike[str] | None = None,
) -> list:
    """Scan modified Python files for hardcoded .artifacts path literals."""
    from .scanners.engine import scan_patch_and_untracked

    return scan_patch_and_untracked(
        candidate_re=_ARTIFACT_LITERAL_CANDIDATE_RE,
        match_line_fn=_match_artifact_line,
        repo_root=repo_root,
        file_glob="*.py",
    )


__all__ = [
    "MERGE_DIR_NAME",
    "MERGE_REPORT_NAME",
    "ArtifactClassification",
    "ArtifactRole",
    "FixturePaths",
    "PhasePaths",
    "ProjectPaths",
    "RunPaths",
    "classify_artifact_path",
    "merge_report_path_in",
    "partition_merge_report_path_in",
    "partition_merge_root_in",
    "resolve_paths",
    "scan_artifact_path_literals",
]
