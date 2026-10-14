"""Tests for XBRL benchmark execution engine."""

from pathlib import Path

from edgar_sec.engine.xbrl.review.benchmark import (
    execute_cohort_benchmark,
    run_benchmark,
)
from edgar_sec.engine.xbrl.discovery.cohort import load_seed_cohort
from edgar_sec.engine.xbrl.taxonomy.domain import load_domain_taxonomy
from edgar_sec.engine.xbrl.evidence.evidence import EvidenceKnowledgeBase
from edgar_sec.engine.xbrl.solve.solver import XbrlConstraintSolver
from tests.support import fixture_path


def test_run_benchmark_seed_cohort() -> None:
    """Verify run_benchmark returns 100% accuracy on seed cohort."""
    cohort = load_seed_cohort(fixture_path("xbrl/seed_cohort.json"))
    tax = load_domain_taxonomy(fixture_path("xbrl/taxonomy"))
    kb = EvidenceKnowledgeBase(taxonomy=tax)
    solver = XbrlConstraintSolver(kb)

    report = run_benchmark(cohort, solver)
    assert report.total_tests > 0
    assert report.passed_tests == report.total_tests
    assert report.accuracy_pct == 100.0


def test_execute_cohort_benchmark(tmp_path: Path) -> None:
    """Verify execute_cohort_benchmark writes JSON report to disk."""
    out_file = tmp_path / "report.json"
    report = execute_cohort_benchmark(
        cohort_source=fixture_path("xbrl/seed_cohort.json"),
        taxonomy_dir=fixture_path("xbrl/taxonomy"),
        output_path=out_file,
    )
    assert report.accuracy_pct == 100.0
    assert out_file.is_file()
