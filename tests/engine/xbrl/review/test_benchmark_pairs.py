"""Tests for the seeded XBRL pair set and its evaluation."""

from pathlib import Path

import pytest

from edgar_sec.engine.xbrl.review.benchmark_pairs import (
    PAIR_SET,
    PairSpec,
    evaluate_pairs,
)
from edgar_sec.engine.xbrl.taxonomy.domain import load_domain_taxonomy
from tests.support.fixtures import fixture_path


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
    from edgar_sec.engine.xbrl.solve.cohort.cohort_lookup import CohortLookup
    from edgar_sec.engine.xbrl.solve.concepts.concept_table import (
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
