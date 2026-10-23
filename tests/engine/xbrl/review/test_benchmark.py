"""Tests for XBRL benchmark execution engine."""

from pathlib import Path

import pytest

from edgar_sec.engine.xbrl.review.benchmark import (
    PAIR_SET,
    CENSUS_EXPECTATIONS,
    CensusExpectation,
    PairSpec,
    evaluate_pairs,
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


def test_pair_set_entries_carry_provenance() -> None:
    """Every seeded pair names its verified specimen; no duplicate seeds."""
    keys = [
        (spec.target, spec.candidate, spec.source_firm, spec.candidate_firm)
        for spec in PAIR_SET
    ]
    assert len(keys) == len(set(keys))
    for spec in PAIR_SET:
        assert spec.provenance
        if spec.incompatibility:
            assert spec.source_firm and spec.candidate_firm
        else:
            assert spec.tier in {"exact", "near", "unrelated"}


@pytest.fixture()
def synthetic_lookup(tmp_path: Path):
    """Two one-filing bundles with payables and a euro-denominated twin."""
    from edgar_sec.domain.identity import AccessionNumber
    from edgar_sec.engine.xbrl.schema.models import XbrlFact
    from edgar_sec.engine.xbrl.solve.cohort_lookup import CohortLookup
    from edgar_sec.engine.xbrl.solve.concept_table import (
        CohortEntry,
        build_cohort_table,
    )
    from edgar_sec.engine.xbrl.storage.storage import write_facts_parquet

    def fact(accession: str, qname: str, value: float, unit: str) -> XbrlFact:
        return XbrlFact(
            accession=AccessionNumber.from_any(accession),
            concept_qname=qname,
            value=value,
            unit=unit,
            period_type="instant",
            instant_date="2024-12-31",
        )

    acc_a, acc_b = "0000000001-24-000001", "0000000002-24-000002"
    path_a = tmp_path / "aaa" / "facts.parquet"
    path_b = tmp_path / "bbb" / "facts.parquet"
    write_facts_parquet(
        [fact(acc_a, "us-gaap:AccountsPayableCurrent", 100.0, "USD")], path_a
    )
    write_facts_parquet(
        [
            fact(acc_b, "us-gaap:AccountsPayableCurrent", 200.0, "EUR"),
            fact(acc_b, "us-gaap:AccountsPayableCurrent", 150.0, "EUR"),
        ],
        path_b,
    )
    entries = (
        CohortEntry(accession=acc_a, facts_path=path_a, firm="AAA"),
        CohortEntry(accession=acc_b, facts_path=path_b, firm="BBB"),
    )
    tax = load_domain_taxonomy(fixture_path("xbrl/taxonomy"))
    lookup = CohortLookup(build_cohort_table(tax, entries), entries)
    yield lookup, fact(acc_a, "us-gaap:AccountsPayableCurrent", 100.0, "USD")
    lookup.close()


def test_evaluate_pairs_synthetic(synthetic_lookup) -> None:
    """Tier and fact pairs pass at their expectations on a synthetic cohort."""
    lookup, source = synthetic_lookup
    pairs = (
        PairSpec(
            "us-gaap:AccountsPayableCurrent",
            "us-gaap:AccountsPayableCurrent",
            "exact",
            "synthetic specimen",
            rule="equality",
        ),
        PairSpec(
            "us-gaap:AccountsPayable",
            "us-gaap:AccountsPayableCurrent",
            "near",
            "synthetic specimen",
            rule="single_modifier_difference",
            direction="specialization",
        ),
        PairSpec(
            "us-gaap:AccountsPayableCurrent",
            "",
            "",
            "synthetic specimen",
            source_firm="AAA",
            candidate_firm="BBB",
            incompatibility="unit",
        ),
    )
    report = evaluate_pairs(
        lookup, pairs, {("AAA", "us-gaap:AccountsPayableCurrent"): source}
    )
    assert report.passed_all
    assert report.passed == 3


def test_evaluate_pairs_names_a_tier_regression(synthetic_lookup) -> None:
    """A pair whose live tier disagrees with its seed fails, naming the pair."""
    lookup, _source = synthetic_lookup
    pairs = (
        PairSpec(
            "us-gaap:AccountsPayable",
            "us-gaap:AccountsPayableCurrent",
            "exact",
            "synthetic specimen",
            rule="equality",
        ),
    )
    report = evaluate_pairs(lookup, pairs)
    assert not report.passed_all
    assert report.passed == 0
    assert "AccountsPayableCurrent" in report.failures[0]
    assert "expected tier=exact" in report.failures[0]
