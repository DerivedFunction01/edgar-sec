"""Standard path resolvers and filenames for review runs and diffs."""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from pathlib import Path

from edgar_sec.foundation.runtime.paths import (
    dataset_root,
    validate_path_component,
    validate_safe_id,
)

REVIEW_RUNS_DIR = "review-runs"
CASES_DIR = "cases"
SUMMARY_FILE = "summary.txt"
DIFF_MANIFEST_FILE = "diff_manifest.json"
REVIEW_MANIFEST_FILE = "manifest.json"
PIPELINE_REVIEW_MANIFEST_FILE = "manifest.jsonl"
REVIEW_SUMMARY_FILE = "summary.json"
PATCHES_DIR = "patches"
DIFF_DIR_PREFIX = "diff-"
RUN_DIR_PREFIX = "run-"


@dataclass(frozen=True, slots=True)
class ReviewPaths:
    root: Path
    manifest_filename: str = REVIEW_MANIFEST_FILE
    cases_directory: str = CASES_DIR
    staging_directory: str = ".staging"

    def __post_init__(self) -> None:
        object.__setattr__(self, "root", Path(self.root))
        validate_path_component(self.manifest_filename, "manifest filename")
        validate_path_component(self.cases_directory, "cases directory")
        validate_safe_id(self.staging_directory, "staging directory")

    @property
    def review_id(self) -> str:
        return self.root.name

    @property
    def manifest_path(self) -> Path:
        return self.root / self.manifest_filename

    @property
    def cases_root(self) -> Path:
        return self.root / self.cases_directory

    @property
    def cases_dir(self) -> Path:
        return self.cases_root

    def case_dir(self, case_id: str) -> Path:
        return self.cases_root / validate_safe_id(case_id, "case_id")

    def case_staging_root(self) -> Path:
        return self.root / self.staging_directory

    @property
    def summary_file(self) -> Path:
        return self.root / SUMMARY_FILE

    @property
    def diff_manifest_file(self) -> Path:
        return self.root / DIFF_MANIFEST_FILE

    @property
    def patches_dir(self) -> Path:
        return self.root / PATCHES_DIR

    def patch_file(self, patch_id: str) -> Path:
        safe_patch_id = validate_safe_id(patch_id, "patch_id")
        return self.patches_dir / f"{safe_patch_id}.patch"


def review_runs_root(artifacts_root: Path | str, dataset: str) -> Path:
    return dataset_root(artifacts_root, dataset) / REVIEW_RUNS_DIR


def review_run_paths(
    artifacts_root: Path | str, dataset: str, review_id: str
) -> ReviewPaths:
    root = review_runs_root(artifacts_root, dataset) / validate_safe_id(
        review_id, "review_id"
    )
    return ReviewPaths(root, PIPELINE_REVIEW_MANIFEST_FILE)


def new_review_run_id() -> str:
    """Generate a chronological review run identifier."""
    now = datetime.datetime.now(datetime.timezone.utc)
    return now.strftime("%Y%m%d_%H%M%S")


def new_review_run_dir(runs_root: Path | str) -> Path:
    """Return a new chronological review run directory path."""
    return Path(runs_root) / f"{RUN_DIR_PREFIX}{new_review_run_id()}"


def new_diff_dir(runs_root: Path | str) -> Path:
    """Return a new chronological diff run directory path."""
    return Path(runs_root) / f"{DIFF_DIR_PREFIX}{new_review_run_id()}"


def is_diff_run_dir(path: Path) -> bool:
    """Return whether a path represents a diff run directory."""
    return path.name.startswith(DIFF_DIR_PREFIX)


__all__ = [
    "CASES_DIR",
    "DIFF_DIR_PREFIX",
    "DIFF_MANIFEST_FILE",
    "PATCHES_DIR",
    "PIPELINE_REVIEW_MANIFEST_FILE",
    "REVIEW_MANIFEST_FILE",
    "REVIEW_RUNS_DIR",
    "REVIEW_SUMMARY_FILE",
    "ReviewPaths",
    "RUN_DIR_PREFIX",
    "SUMMARY_FILE",
    "is_diff_run_dir",
    "new_diff_dir",
    "new_review_run_dir",
    "new_review_run_id",
    "review_run_paths",
    "review_runs_root",
]
