"""Standard path resolvers and filenames for review runs and diffs."""

from __future__ import annotations

import datetime
from dataclasses import dataclass
from pathlib import Path

from edgar_sec.foundation.runtime.fixtures import validate_fixture_component

REVIEW_DIR = "review"
CASES_DIR = "cases"
SUMMARY_FILE = "summary.txt"
DIFF_MANIFEST_FILE = "diff_manifest.json"
REVIEW_MANIFEST_FILE = "manifest.json"
REVIEW_SUMMARY_FILE = "summary.json"
PATCHES_DIR = "patches"
DIFF_DIR_PREFIX = "diff-"
RUN_DIR_PREFIX = "run-"


def review_runs_root(artifacts_root: Path | str, dataset: str) -> Path:
    """Return the base directory for a dataset's review runs."""
    dataset = validate_fixture_component(dataset, "dataset")
    return Path(artifacts_root) / dataset / REVIEW_DIR


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


@dataclass(frozen=True, slots=True)
class ReviewPaths:
    """Path resolver for a single review run or review diff directory."""

    run_dir: Path

    def __post_init__(self) -> None:
        object.__setattr__(self, "run_dir", Path(self.run_dir))

    @property
    def cases_dir(self) -> Path:
        return self.run_dir / CASES_DIR

    def case_dir(self, case_id: str) -> Path:
        return self.cases_dir / case_id

    @property
    def summary_file(self) -> Path:
        return self.run_dir / SUMMARY_FILE

    @property
    def review_manifest_file(self) -> Path:
        return self.run_dir / REVIEW_MANIFEST_FILE

    @property
    def review_summary_file(self) -> Path:
        return self.run_dir / REVIEW_SUMMARY_FILE

    @property
    def diff_manifest_file(self) -> Path:
        return self.run_dir / DIFF_MANIFEST_FILE

    @property
    def patches_dir(self) -> Path:
        return self.run_dir / PATCHES_DIR

    def patch_file(self, case_id: str) -> Path:
        return self.patches_dir / f"{case_id}.patch"
