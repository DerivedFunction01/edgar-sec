"""Single owner for XBRL review artifact, runtime, and transient paths."""

from __future__ import annotations

from pathlib import Path

from edgar_sec.engine.xbrl.discovery.cohort import (
    CORPUS_DIR,
    corpus_root as _discovery_corpus_root,
)
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
PRESENTATION_ARCS_FILE = "presentation_arcs.parquet"
CALCULATION_ARCS_FILE = "calculation_arcs.parquet"
WORK_ORDER_FILE = "work_order.parquet"
COHORT_ACCESSIONS_FILE = "cohort_accessions.parquet"
PROJECTION_MANIFEST_FILE = "projection_manifest.json"
UNIFICATION_RULES_DB_FILE = "unification_rules.duckdb"
DEFAULT_SP100_COHORT_FILE = "sp100_cohort.json"

PIPELINE_ROOT = Path(__file__).resolve().parent
FIXTURES_DIR = PIPELINE_ROOT / "fixtures"
REVIEW_CORPUS_DIR = "review"


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
    def corpus_root(self) -> Path:
        """Corpus root anchored at this instance's artifacts root. :no-docgen:"""
        return corpus_root(self.artifacts_root)

    @property
    def builtin_fixtures_dir(self) -> Path:
        """Cohort registry home: the corpus root's review dir when it holds
        the sp100 registry, else this package's fixtures. :no-docgen:"""
        external = review_corpus_dir(self.artifacts_root)
        if (external / DEFAULT_SP100_COHORT_FILE).is_file():
            return external
        return FIXTURES_DIR

    @property
    def default_sp100_cohort_path(self) -> Path:
        """Package-local S&P 100 cohort input. :no-docgen:"""
        return self.builtin_fixtures_dir / DEFAULT_SP100_COHORT_FILE

    @property
    def snapshots_root(self) -> Path:
        return foundation_paths.snapshots_root(self.artifacts_root, DATASET)

    def snapshot_root(self, snapshot_id: str) -> Path:
        return self.snapshots_root / foundation_paths.validate_safe_id(
            snapshot_id, "snapshot_id"
        )

    def snapshot_relation_dir(self, snapshot_id: str, relation: str) -> Path:
        return DAGPaths(self.snapshots_root).relation_dir(snapshot_id, relation)

    def snapshot_part_path(
        self, snapshot_id: str, relation: str, part_index: int
    ) -> Path:
        return DAGPaths(self.snapshots_root).part_file(
            snapshot_id, relation, part_index
        )

    @property
    def review_runs_root(self) -> Path:
        return review_runs_root(self.artifacts_root, DATASET)

    def review_paths(self, review_id: str) -> ReviewPaths:
        return review_run_paths(self.artifacts_root, DATASET, review_id)

    def review_manifest_path(self, run_id: str) -> Path:
        return self.review_paths(run_id).manifest_path

    def review_case_dir(self, run_id: str, accession: str) -> Path:
        return self.review_paths(run_id).case_dir(accession)

    def review_case_solved_nodes_path(self, run_id: str, accession: str) -> Path:
        return self.review_case_dir(run_id, accession) / SOLVED_NODES_FILE

    def review_case_rule_trace_path(self, run_id: str, accession: str) -> Path:
        return self.review_case_dir(run_id, accession) / RULE_TRACE_FILE

    def review_case_quarantine_path(self, run_id: str, accession: str) -> Path:
        return self.review_case_dir(run_id, accession) / QUARANTINE_FILE

    def review_case_hypotheses_path(self, run_id: str, accession: str) -> Path:
        return self.review_case_dir(run_id, accession) / HYPOTHESES_FILE

    def review_case_presentation_arcs_path(self, run_id: str, accession: str) -> Path:
        return self.review_case_dir(run_id, accession) / PRESENTATION_ARCS_FILE

    def review_case_calculation_arcs_path(self, run_id: str, accession: str) -> Path:
        return self.review_case_dir(run_id, accession) / CALCULATION_ARCS_FILE

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
        self.run_id = foundation_paths.validate_safe_id(run_id, "run_id")
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
        return (
            self.run_root
            / CHUNKS_DIR
            / foundation_paths.validate_safe_id(chunk_id, "chunk_id")
        )

    def chunk_pointer_path(self, chunk_id: str) -> Path:
        return self.chunk_dir(chunk_id) / POINTER_FILE

    def attempt_dir(self, chunk_id: str, attempt_id: str) -> Path:
        safe_attempt = foundation_paths.validate_safe_id(attempt_id, "attempt_id")
        return self.chunk_dir(chunk_id) / f"{ATTEMPT_PREFIX}{safe_attempt}"

    def attempt_solved_nodes_path(self, chunk_id: str, attempt_id: str) -> Path:
        return self.attempt_dir(chunk_id, attempt_id) / SOLVED_NODES_FILE

    def attempt_rule_trace_path(self, chunk_id: str, attempt_id: str) -> Path:
        return self.attempt_dir(chunk_id, attempt_id) / RULE_TRACE_FILE

    def attempt_quarantine_path(self, chunk_id: str, attempt_id: str) -> Path:
        return self.attempt_dir(chunk_id, attempt_id) / QUARANTINE_FILE

    def attempt_hypotheses_path(self, chunk_id: str, attempt_id: str) -> Path:
        return self.attempt_dir(chunk_id, attempt_id) / HYPOTHESES_FILE

    def attempt_presentation_arcs_path(self, chunk_id: str, attempt_id: str) -> Path:
        return self.attempt_dir(chunk_id, attempt_id) / PRESENTATION_ARCS_FILE

    def attempt_calculation_arcs_path(self, chunk_id: str, attempt_id: str) -> Path:
        return self.attempt_dir(chunk_id, attempt_id) / CALCULATION_ARCS_FILE

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


def corpus_root(artifacts_root: Path | str | None = None) -> Path:
    """Corpus root for the review plane: the discovery corpus seam's root.

    An explicit artifacts root that differs from the resolved default
    anchors the convention (``<root>/xbrl/corpus``) at that root instead.
    """
    if artifacts_root is not None:
        anchored = Path(artifacts_root)
        if anchored.resolve() != foundation_paths.resolve_paths().artifacts_root:
            return foundation_paths.dataset_root(anchored, DATASET) / CORPUS_DIR
    return _discovery_corpus_root()


def review_corpus_dir(artifacts_root: Path | str | None = None) -> Path:
    """Review registries' corpus home, ``<corpus_root>/review`` — distinct
    from the top level, where the discovery registries live, so the review
    sp100 registry never conflates with the discovery one of the same name.
    """
    return corpus_root(artifacts_root) / REVIEW_CORPUS_DIR


def default_sp100_cohort_path(artifacts_root: Path | str | None = None) -> Path:
    """Default S&P 100 cohort path: corpus review dir, else package fixtures."""
    return xbrl_paths(artifacts_root).default_sp100_cohort_path


__all__ = [
    "ATTEMPT_PREFIX",
    "CALCULATION_ARCS_FILE",
    "CHUNKS_DIR",
    "COHORT_ACCESSIONS_FILE",
    "DATASET",
    "DEFAULT_SP100_COHORT_FILE",
    "FIXTURES_DIR",
    "HYPOTHESES_FILE",
    "MANIFEST_FILE",
    "PLAN_TARGETS_DIR",
    "POINTER_FILE",
    "PRESENTATION_ARCS_FILE",
    "PROJECTION_MANIFEST_FILE",
    "PUBLICATION_LOCK_FILE",
    "QUARANTINE_FILE",
    "REVIEW_CORPUS_DIR",
    "RULE_TRACE_FILE",
    "RUN_LOCK_FILE",
    "RUN_MANIFEST_FILE",
    "SOLVED_NODES_FILE",
    "UNIFICATION_RULES_DB_FILE",
    "WORK_ORDER_FILE",
    "XbrlPaths",
    "XbrlRunPaths",
    "corpus_root",
    "default_sp100_cohort_path",
    "resolve_filing_catalog_paths",
    "review_corpus_dir",
    "xbrl_paths",
    "xbrl_run_paths",
]
