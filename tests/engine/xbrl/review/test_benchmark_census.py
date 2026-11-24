"""Tests for XBRL census summary aggregation and scoring."""

import json
from pathlib import Path

from edgar_sec.engine.xbrl.review import census_expectations
from edgar_sec.engine.xbrl.review.benchmark_census import (
    score_census,
    summarize_census,
)
from edgar_sec.engine.xbrl.review.census_expectations import (
    CENSUS_EXPECTATIONS,
    CensusExpectation,
)


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


def test_probe_expectation_comes_from_its_record() -> None:
    """The probe entry equals its data record; no probe literal stays inline."""
    module_path = Path(census_expectations.__file__)
    record = json.loads(
        module_path.with_name("census_probe_expectation.json").read_text(
            encoding="utf-8"
        )
    )
    row = record["probe"]
    assert CENSUS_EXPECTATIONS["probe"] == CensusExpectation(
        n=row["n"],
        correct=row["correct"],
        honest=row["honest"],
        surfaced_conflicts=row["surfaced_conflicts"],
    )
    assert '"probe": CensusExpectation' not in module_path.read_text(encoding="utf-8")
