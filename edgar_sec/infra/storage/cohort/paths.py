"""Cohort storage layout and bounded path operations."""

from __future__ import annotations

import os
import re
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from edgar_sec.foundation.runtime.paths import ProjectPaths, resolve_paths

COHORTS_DIR_NAME = "cohorts"
CATALOG_DB_NAME = "cohorts.sqlite"
DATASET_FILE_NAME = "ciks.parquet"
MANIFEST_FILE_NAME = "cohort.json"
STAGING_PREFIX = ".stage-"
_SAFE_ID_RE = re.compile(r"^[a-zA-Z0-9_.-]{3,64}$")


@dataclass(frozen=True, slots=True)
class CohortPaths:
    artifacts_root: Path

    def __post_init__(self) -> None:
        object.__setattr__(self, "artifacts_root", Path(self.artifacts_root))

    @property
    def cohorts_root(self) -> Path:
        return self.artifacts_root / COHORTS_DIR_NAME

    @property
    def catalog_file(self) -> Path:
        return self.cohorts_root / CATALOG_DB_NAME

    def cohort_dir(self, cohort_id: str) -> Path:
        if (
            not isinstance(cohort_id, str)
            or not _SAFE_ID_RE.fullmatch(cohort_id)
            or ".." in cohort_id
        ):
            raise ValueError(f"Invalid or unsafe cohort identifier: {cohort_id!r}")
        root = self.cohorts_root.resolve()
        path = (self.cohorts_root / cohort_id).resolve()
        if path.parent != root or path.name != cohort_id:
            raise ValueError(f"Cohort directory escapes root: {cohort_id!r}")
        return path

    def cohort_dataset_file(self, cohort_id: str) -> Path:
        return self.cohort_dir(cohort_id) / DATASET_FILE_NAME

    def cohort_manifest_file(self, cohort_id: str) -> Path:
        return self.cohort_dir(cohort_id) / MANIFEST_FILE_NAME

    def relative_path(self, path: Path | str) -> str:
        root = self.cohorts_root.resolve()
        target = Path(path).resolve()
        try:
            relative = target.relative_to(root)
        except ValueError as exc:
            raise ValueError(f"Path is outside cohorts root: {path!r}") from exc
        if not relative.parts:
            raise ValueError("A cohort artifact path cannot be the storage root")
        return relative.as_posix()

    def resolve_relative_path(self, relative_path: str | Path) -> Path:
        raw = str(relative_path)
        candidate = PurePosixPath(raw)
        if (
            not raw
            or "\\" in raw
            or ":" in raw
            or candidate.is_absolute()
            or candidate.as_posix() != raw
            or any(part in {"", ".", ".."} for part in candidate.parts)
        ):
            raise ValueError(f"Invalid relative cohort path: {raw!r}")
        root = self.cohorts_root.resolve()
        resolved = (root.joinpath(*candidate.parts)).resolve()
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise ValueError(f"Cohort path escapes root: {raw!r}") from exc
        return resolved

    def create_staging_dir(self, cohort_id: str) -> Path:
        self.cohort_dir(cohort_id)
        self.cohorts_root.mkdir(parents=True, exist_ok=True)
        stage = self.cohorts_root / f"{STAGING_PREFIX}{cohort_id}-{uuid.uuid4().hex}"
        stage.mkdir()
        return stage

    def publish_staging_dir(self, cohort_id: str, staging_dir: Path | str) -> Path:
        self.cohort_dir(cohort_id)
        stage = Path(staging_dir).resolve()
        root = self.cohorts_root.resolve()
        if stage.parent != root or not stage.name.startswith(
            f"{STAGING_PREFIX}{cohort_id}-"
        ):
            raise ValueError(f"Invalid staging directory: {staging_dir!r}")
        target = self.cohort_dir(cohort_id)
        if target.exists():
            raise FileExistsError(target)
        os.replace(stage, target)
        return target

    def list_staging_dirs(self) -> list[Path]:
        if not self.cohorts_root.is_dir():
            return []
        return sorted(
            (
                entry
                for entry in self.cohorts_root.iterdir()
                if entry.is_dir() and entry.name.startswith(STAGING_PREFIX)
            ),
            key=lambda entry: entry.name,
        )

    def remove_staging_dir(self, staging_dir: Path | str) -> None:
        stage = Path(staging_dir).resolve()
        if stage.parent != self.cohorts_root.resolve() or not stage.name.startswith(
            STAGING_PREFIX
        ):
            raise ValueError(f"Invalid staging directory: {staging_dir!r}")
        if stage.is_dir():
            shutil.rmtree(stage)


def resolve_cohort_paths(
    artifacts_root: Path | str | None = None,
    *,
    project_paths: ProjectPaths | None = None,
) -> CohortPaths:
    if artifacts_root is not None:
        root = Path(artifacts_root)
    elif project_paths is not None:
        root = project_paths.artifacts_root
    else:
        root = resolve_paths().artifacts_root
    return CohortPaths(root)


__all__ = [
    "CATALOG_DB_NAME",
    "COHORTS_DIR_NAME",
    "CohortPaths",
    "DATASET_FILE_NAME",
    "MANIFEST_FILE_NAME",
    "STAGING_PREFIX",
    "resolve_cohort_paths",
]
