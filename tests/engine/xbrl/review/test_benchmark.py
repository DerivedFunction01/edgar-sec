"""Tests for XBRL benchmark execution engine."""

from pathlib import Path

from edgar_sec.engine.xbrl.review.benchmark import (
    CENSUS_EXPECTATIONS,
    CensusExpectation,
    execute_cohort_benchmark,
    run_benchmark,
    score_census,
    summarize_census,
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


def _evaluation(population: str, classification: str, status: str = "REPORTED") -> dict:
    """One minimal evaluation record for summary/score tests."""
    return {
        "population": population,
        "firm": "msft",
        "term": "revenue",
        "mode": "REPORTED_ONLY",
        "facade": {"status": status, "value": 1.0},
        "classification": classification,
        "replay_mismatch": False,
    }


def test_score_census_passes_and_names_movements() -> None:
    """Scoring passes an exact summary and fails naming any moved count."""
    evaluations = [
        _evaluation("probe", "correct"),
        _evaluation("probe", "honest-faithful", status="AMBIGUOUS"),
    ]
    summary = summarize_census(evaluations)
    expectations = {
        "probe": CensusExpectation(n=2, correct=1, honest=1, surfaced_conflicts=0)
    }
    assert score_census(summary, expectations).passed
    moved = summarize_census([_evaluation("probe", "correct")] + evaluations)
    score = score_census(moved, expectations)
    assert not score.passed
    assert any("correct" in failure for failure in score.failures)


def test_score_census_rejects_adverse_and_replay_drift() -> None:
    """Adverse classifications and replay mismatches each fail the gate."""
    expectations = {
        "probe": CensusExpectation(n=1, correct=0, honest=1, surfaced_conflicts=0)
    }
    adverse = summarize_census([_evaluation("probe", "wrong-span")])
    assert not score_census(adverse, expectations).passed
    drifted = _evaluation("probe", "honest-faithful", status="AMBIGUOUS")
    drifted["replay_mismatch"] = True
    score = score_census(summarize_census([drifted]), expectations)
    assert not score.passed
    assert any("replay_mismatches" in failure for failure in score.failures)


def test_census_expectations_cover_the_full_census() -> None:
    """Every scored population's expectation accounts for all its evaluations."""
    for expectation in CENSUS_EXPECTATIONS.values():
        assert expectation.correct + expectation.honest == expectation.n
