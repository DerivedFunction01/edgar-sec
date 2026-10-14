"""Path layout definitions for the XBRL review and staging pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from edgar_sec.foundation.runtime.paths import ProjectPaths, resolve_paths
from edgar_sec.infra.storage.review.paths import ReviewPaths

XBRL_DIR = "xbrl"
REVIEW_RUNS_DIR = "review-runs"
STAGING_LAKE_DIR = "staging_lake"
COHORTS_DIR = "cohorts"
UNIFICATION_RULES_DB_FILE = "unification_rules.duckdb"
BENCHMARK_REPORT_FILE = "benchmark_report.json"
DEFAULT_SEED_COHORT_FILE = "seed_cohort.json"
DEFAULT_SP100_COHORT_FILE = "sp100_cohort.json"


@dataclass(frozen=True, slots=True)
class XbrlReviewPaths:
    """Artifact and review path layout for XBRL review runs and staging."""

    project: ProjectPaths

    @property
    def artifacts_root(self) -> Path:
        """Root directory for project artifacts."""
        return self.project.artifacts_root

    @property
    def repo_root(self) -> Path:
        """Root directory for the git repository."""
        return self.project.repo_root

    @property
    def pipeline_root(self) -> Path:
        """Root directory for all published XBRL review artifacts."""
        return self.artifacts_root / XBRL_DIR

    @property
    def review_runs_dir(self) -> Path:
        """Directory housing historical review run cases and diffs."""
        return self.pipeline_root / REVIEW_RUNS_DIR

    @property
    def staging_lake_dir(self) -> Path:
        """Directory housing staged Parquet facts and diagnostic tables."""
        return self.pipeline_root / STAGING_LAKE_DIR

    @property
    def cohorts_dir(self) -> Path:
        """Directory housing pipeline review cohorts."""
        return self.pipeline_root / COHORTS_DIR

    @property
    def unification_rules_db_path(self) -> Path:
        """Path to DuckDB database containing promoted unification rules."""
        return self.pipeline_root / UNIFICATION_RULES_DB_FILE

    @property
    def default_benchmark_report_path(self) -> Path:
        """Path to default benchmark report JSON."""
        return self.pipeline_root / BENCHMARK_REPORT_FILE

    @property
    def default_seed_cohort_path(self) -> Path:
        """Default seed cohort fixture path."""
        repo_fixture = self.repo_root / "tests" / "fixtures" / "xbrl" / DEFAULT_SEED_COHORT_FILE
        if repo_fixture.is_file():
            return repo_fixture
        return self.repo_root / "edgar_sec" / "engine" / "xbrl" / "taxonomy" / DEFAULT_SEED_COHORT_FILE

    @property
    def default_sp100_cohort_path(self) -> Path:
        """Default S&P 100 cohort fixture path."""
        repo_fixture = self.repo_root / "tests" / "fixtures" / "xbrl" / DEFAULT_SP100_COHORT_FILE
        if repo_fixture.is_file():
            return repo_fixture
        repo_tax_fixture = self.repo_root / "tests" / "fixtures" / "xbrl" / "taxonomy" / DEFAULT_SP100_COHORT_FILE
        if repo_tax_fixture.is_file():
            return repo_tax_fixture
        return self.repo_root / "edgar_sec" / "engine" / "xbrl" / "taxonomy" / DEFAULT_SP100_COHORT_FILE

    def review_run_paths(self, run_id: str) -> ReviewPaths:
        """Return ReviewPaths handle for a specific chronological review run."""
        return ReviewPaths(self.review_runs_dir / run_id)

    def ensure_directories(self) -> None:
        """Create standard pipeline artifact directories if nonexistent."""
        self.pipeline_root.mkdir(parents=True, exist_ok=True)
        self.review_runs_dir.mkdir(parents=True, exist_ok=True)
        self.staging_lake_dir.mkdir(parents=True, exist_ok=True)


def resolve_xbrl_review_paths(
    artifacts_root: Path | str | None = None,
    repo_root: Path | str | None = None,
) -> XbrlReviewPaths:
    """Resolve standard paths layout for XBRL review pipeline."""
    project = resolve_paths(
        artifacts_root=Path(artifacts_root) if artifacts_root else None,
        repo_root=Path(repo_root) if repo_root else None,
    )
    return XbrlReviewPaths(project=project)
