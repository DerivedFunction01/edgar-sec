"""Single owner for XBRL review artifact, runtime, and transient paths."""

from __future__ import annotations

import hashlib
from pathlib import Path

import edgar_sec.foundation.runtime.fixtures as foundation_fixtures
import edgar_sec.foundation.runtime.paths as foundation_paths
from edgar_sec.foundation.runtime.paths import (
    ATTEMPT_PREFIX,
    CHUNKS_DIR,
    MANIFEST_FILE,
    POINTER_FILE,
    PUBLICATION_LOCK_FILE,
    RUN_LOCK_FILE,
    RUN_MANIFEST_FILE,
)
from edgar_sec.infra.storage.dag.paths import DAGPaths
from edgar_sec.infra.storage.review.paths import (
    ReviewPaths,
    review_run_paths,
    review_runs_root,
)
from edgar_sec.pipelines.filing_catalog.paths import (
    PLAN_TARGETS_DIR,
    resolve_filing_catalog_paths,
)

DATASET = "xbrl"

SOLVED_NODES_FILE = "solved_nodes.parquet"
RULE_TRACE_FILE = "rule_trace.parquet"
QUARANTINE_FILE = "quarantine.parquet"
HYPOTHESES_FILE = "hypotheses.parquet"
WORK_ORDER_FILE = "work_order.parquet"
COHORT_ACCESSIONS_FILE = "cohort_accessions.parquet"
PROJECTION_MANIFEST_FILE = "projection_manifest.json"
UNIFICATION_RULES_DB_FILE = "unification_rules.duckdb"
DEFAULT_SEED_COHORT_FILE = "seed_cohort.json"
DEFAULT_SP100_COHORT_FILE = "sp100_cohort.json"

PIPELINE_ROOT = Path(__file__).resolve().parent
FIXTURES_DIR = PIPELINE_ROOT / "fixtures"


def _validate_id(value: str, label: str) -> str:
    return foundation_paths.validate_safe_id(value, label)


class XbrlPaths:
    """Validated paths for XBRL-owned snapshot, review, and transient artifacts."""

    __slots__ = ("artifacts_root",)

    def __init__(self, artifacts_root: Path | str) -> None:
        self.artifacts_root = Path(artifacts_root).resolve()

    @property
    def fixtures_root(self) -> Path:
        """Root directory for XBRL fixture stores."""
        return foundation_fixtures.fixtures_root(self.artifacts_root, DATASET)

    def fixture_root(self, fixture_id: str) -> Path:
        """Root directory for one XBRL fixture."""
        return self.fixture_paths(fixture_id).root

    def fixture_paths(self, fixture_id: str) -> foundation_fixtures.FixturePaths:
        return foundation_fixtures.fixture_paths(
            self.artifacts_root, DATASET, fixture_id
        )

    def fixture_manifest_path(self, fixture_id: str) -> Path:
        return self.fixture_paths(fixture_id).manifest_path

    def fixture_database_path(self, fixture_id: str) -> Path:
        return self.fixture_paths(fixture_id).storage_path

    @property
    def builtin_fixtures_dir(self) -> Path:
        """Package-local cohort inputs; not published artifacts. :no-docgen:"""
        return FIXTURES_DIR

    @property
    def default_seed_cohort_path(self) -> Path:
        """Package-local seed cohort input. :no-docgen:"""
        return self.builtin_fixtures_dir / DEFAULT_SEED_COHORT_FILE

    @property
    def default_sp100_cohort_path(self) -> Path:
        """Package-local S&P 100 cohort input. :no-docgen:"""
        return self.builtin_fixtures_dir / DEFAULT_SP100_COHORT_FILE

    @property
    def snapshots_root(self) -> Path:
        return foundation_paths.snapshots_root(self.artifacts_root, DATASET)

    def snapshot_root(self, snapshot_id: str) -> Path:
        return self.snapshots_root / _validate_id(snapshot_id, "snapshot_id")

    @property
    def review_runs_root(self) -> Path:
        return review_runs_root(self.artifacts_root, DATASET)

    def review_paths(self, review_id: str) -> ReviewPaths:
        return review_run_paths(self.artifacts_root, DATASET, review_id)

    @property
    def transient_root(self) -> Path:
        return foundation_paths.transient_dataset_root(self.artifacts_root, DATASET)

    @property
    def unification_rules_db_path(self) -> Path:
        return (
            foundation_paths.dataset_root(self.artifacts_root, DATASET)
            / UNIFICATION_RULES_DB_FILE
        )

    @property
    def catalog_file(self) -> Path:
        """SQLite DAG catalog database for published XBRL snapshots."""
        return DAGPaths(self.snapshots_root).catalog_file

    @property
    def publication_lock_path(self) -> Path:
        return self.snapshots_root / PUBLICATION_LOCK_FILE


class XbrlRunPaths:
    """Validated path methods for one transient XBRL execution run."""

    __slots__ = ("artifacts_root", "run_id", "run_root")

    def __init__(self, artifacts_root: Path, run_id: str) -> None:
        self.artifacts_root = Path(artifacts_root)
        self.run_id = _validate_id(run_id, "run_id")
        self.run_root = foundation_paths.transient_dir(
            self.artifacts_root, DATASET, self.run_id
        )

    @property
    def snapshots_root(self) -> Path:
        return foundation_paths.snapshots_root(self.artifacts_root, DATASET)

    def run_manifest_path(self) -> Path:
        return self.run_root / RUN_MANIFEST_FILE

    def lock_path(self) -> Path:
        return self.run_root / RUN_LOCK_FILE

    def work_order_path(self) -> Path:
        return self.run_root / WORK_ORDER_FILE

    def cohort_accessions_path(self) -> Path:
        return self.run_root / COHORT_ACCESSIONS_FILE

    def projection_manifest_path(self) -> Path:
        return self.run_root / PROJECTION_MANIFEST_FILE

    def chunk_dir(self, chunk_id: str) -> Path:
        return self.run_root / CHUNKS_DIR / _validate_id(chunk_id, "chunk_id")

    def chunk_pointer_path(self, chunk_id: str) -> Path:
        return self.chunk_dir(chunk_id) / POINTER_FILE

    def attempt_dir(self, chunk_id: str, attempt_id: str) -> Path:
        safe_attempt = _validate_id(attempt_id, "attempt_id")
        return self.chunk_dir(chunk_id) / f"{ATTEMPT_PREFIX}{safe_attempt}"

    def attempt_solved_nodes_path(self, chunk_id: str, attempt_id: str) -> Path:
        return self.attempt_dir(chunk_id, attempt_id) / SOLVED_NODES_FILE

    def attempt_rule_trace_path(self, chunk_id: str, attempt_id: str) -> Path:
        return self.attempt_dir(chunk_id, attempt_id) / RULE_TRACE_FILE

    def attempt_quarantine_path(self, chunk_id: str, attempt_id: str) -> Path:
        return self.attempt_dir(chunk_id, attempt_id) / QUARANTINE_FILE

    def attempt_hypotheses_path(self, chunk_id: str, attempt_id: str) -> Path:
        return self.attempt_dir(chunk_id, attempt_id) / HYPOTHESES_FILE

    def attempt_manifest_path(self, chunk_id: str, attempt_id: str) -> Path:
        return self.attempt_dir(chunk_id, attempt_id) / MANIFEST_FILE


def xbrl_run_paths(artifacts_root: Path | str, run_id: str) -> XbrlRunPaths:
    """Construct validated XBRL run paths from an artifacts root and run id."""
    return XbrlRunPaths(Path(artifacts_root), run_id)


def xbrl_paths(artifacts_root: Path | str | None = None) -> XbrlPaths:
    """Construct XBRL artifact paths from the selected artifacts root."""
    root = (
        Path(artifacts_root)
        if artifacts_root is not None
        else foundation_paths.resolve_paths().artifacts_root
    )
    return XbrlPaths(root)


def default_seed_cohort_path(artifacts_root: Path | str | None = None) -> Path:
    """Return default seed cohort fixture path."""
    return xbrl_paths(artifacts_root).default_seed_cohort_path


def default_sp100_cohort_path(artifacts_root: Path | str | None = None) -> Path:
    """Return default S&P 100 cohort fixture path."""
    return xbrl_paths(artifacts_root).default_sp100_cohort_path


def snapshot_id_for(parent_snapshot_id: str | None, digest: str) -> str:
    """Derive an immutable snapshot id from its parent and content digest."""
    content = f"{parent_snapshot_id or ''}:{digest}"
    return f"snapshot-{hashlib.sha256(content.encode('utf-8')).hexdigest()[:16]}"


__all__ = [
    "ATTEMPT_PREFIX",
    "CHUNKS_DIR",
    "COHORT_ACCESSIONS_FILE",
    "DATASET",
    "DEFAULT_SEED_COHORT_FILE",
    "DEFAULT_SP100_COHORT_FILE",
    "FIXTURES_DIR",
    "HYPOTHESES_FILE",
    "MANIFEST_FILE",
    "PLAN_TARGETS_DIR",
    "POINTER_FILE",
    "PROJECTION_MANIFEST_FILE",
    "PUBLICATION_LOCK_FILE",
    "QUARANTINE_FILE",
    "RULE_TRACE_FILE",
    "RUN_LOCK_FILE",
    "RUN_MANIFEST_FILE",
    "SOLVED_NODES_FILE",
    "UNIFICATION_RULES_DB_FILE",
    "WORK_ORDER_FILE",
    "XbrlPaths",
    "XbrlRunPaths",
    "default_seed_cohort_path",
    "default_sp100_cohort_path",
    "resolve_filing_catalog_paths",
    "snapshot_id_for",
    "xbrl_paths",
    "xbrl_run_paths",
]
