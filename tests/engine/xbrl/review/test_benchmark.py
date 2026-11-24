"""Tests for XBRL benchmark execution engine."""

from pathlib import Path

from edgar_sec.engine.xbrl.review.benchmark import (
    execute_cohort_benchmark,
    run_benchmark,
)
from edgar_sec.engine.xbrl.review.chains import CHAIN_SET
from edgar_sec.engine.xbrl.discovery.cohort import load_seed_cohort
from edgar_sec.engine.xbrl.taxonomy.domain import load_domain_taxonomy
from edgar_sec.engine.xbrl.evidence.evidence import EvidenceKnowledgeBase
from edgar_sec.engine.xbrl.solve.core.solver import XbrlConstraintSolver
from tests.support.fixtures import cohort_registry_path, fixture_path


def test_run_benchmark_seed_cohort() -> None:
    """Verify run_benchmark returns 100% accuracy on seed cohort."""
    cohort = load_seed_cohort(cohort_registry_path("seed_cohort.json"))
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
        cohort_source=cohort_registry_path("seed_cohort.json"),
        taxonomy_dir=fixture_path("xbrl/taxonomy"),
        output_path=out_file,
    )
    assert report.accuracy_pct == 100.0
    assert out_file.is_file()


def test_chain_set_entries_carry_provenance() -> None:
    """Every seeded chain names its specimen; expectations are well-formed."""
    labels = [spec.label for spec in CHAIN_SET]
    assert len(labels) == len(set(labels))
    statuses = {
        "VERIFIED",
        "REPORTED",
        "CONFLICT",
        "DERIVED",
        "AMBIGUOUS",
        "UNAVAILABLE",
    }
    rungs = {"name", "derived", "filing_local", "default", "gated_claim"}
    for spec in CHAIN_SET:
        assert spec.provenance
        assert spec.mediated_term in {term for _, term in spec.terms}
        assert spec.on_status in statuses and spec.off_status in statuses
        assert spec.on_provenance in rungs and spec.off_provenance in rungs
        if spec.on_provenance in ("filing_local", "gated_claim"):
            assert spec.on_provenance != spec.off_provenance
            assert spec.on_status == spec.off_status
