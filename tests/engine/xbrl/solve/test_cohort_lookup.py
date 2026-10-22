"""Tests for the DuckDB-direct cohort lookup and its grounded specimens."""

from __future__ import annotations

from pathlib import Path

import pytest

from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.engine.xbrl.schema.models import XbrlFact
from edgar_sec.engine.xbrl.solve.cohort_lookup import CohortLookup
from edgar_sec.engine.xbrl.solve.concept_table import (
    CohortEntry,
    build_cohort_table,
    build_concept_table,
)
from edgar_sec.engine.xbrl.storage.storage import write_facts_parquet
from edgar_sec.engine.xbrl.taxonomy.domain import (
    DomainTaxonomy,
    load_domain_taxonomy,
)
from tests.engine.xbrl.solve.conftest import load_seed_cohort, load_seed_facts

_ACC_A = "0000000001-24-000001"
_ACC_B = "0000000002-24-000002"


@pytest.fixture(scope="module")
def taxonomy() -> DomainTaxonomy:
    return load_domain_taxonomy()


def _fact(
    accession: str,
    qname: str,
    value: float,
    unit: str | None,
    period_type: str = "instant",
    instant_date: str | None = "2024-12-31",
    start_date: str | None = None,
    end_date: str | None = None,
) -> XbrlFact:
    return XbrlFact(
        accession=AccessionNumber.from_any(accession),
        concept_qname=qname,
        value=value,
        unit=unit,
        period_type=period_type,
        start_date=start_date,
        end_date=end_date,
        instant_date=instant_date,
    )


@pytest.fixture()
def synthetic_lookup(taxonomy: DomainTaxonomy, tmp_path: Path) -> CohortLookup:
    """Two one-filing bundles exercising every compatibility outcome."""
    path_a = tmp_path / "aaa" / "facts.parquet"
    path_b = tmp_path / "bbb" / "facts.parquet"
    source = _fact(_ACC_A, "us-gaap:AccountsPayableCurrent", 100.0, "USD")
    write_facts_parquet([source], path_a)
    write_facts_parquet(
        [
            _fact(_ACC_B, "us-gaap:AccountsPayableCurrent", 200.0, "USD"),
            _fact(_ACC_B, "us-gaap:AccountsPayableCurrent", 150.0, "EUR"),
            _fact(_ACC_B, "us-gaap:AccruedLiabilitiesCurrent", 50.0, "USD"),
            _fact(
                _ACC_B,
                "us-gaap:LiabilitiesCurrent",
                900.0,
                "USD",
                instant_date="2023-12-31",
            ),
            _fact(
                _ACC_B,
                "us-gaap:OtherLiabilitiesCurrent",
                700.0,
                "USD",
                period_type="duration",
                instant_date=None,
                start_date="2024-01-01",
                end_date="2024-12-31",
            ),
        ],
        path_b,
    )
    entries = (
        CohortEntry(accession=_ACC_A, facts_path=path_a, firm="AAA"),
        CohortEntry(accession=_ACC_B, facts_path=path_b, firm="BBB"),
    )
    table = build_cohort_table(taxonomy, entries)
    lookup = CohortLookup(table, entries)
    yield lookup
    lookup.close()


def test_equivalents_expand_ranked_pairs(synthetic_lookup: CohortLookup) -> None:
    """Same-qname pairs at other firms are the primary exact candidates."""
    candidates = synthetic_lookup.equivalents("us-gaap:AccountsPayableCurrent")
    pairs = {(item.accession, item.qname) for item in candidates}
    assert (_ACC_B, "us-gaap:AccountsPayableCurrent") in pairs
    exact = [
        item for item in candidates if item.qname == "us-gaap:AccountsPayableCurrent"
    ]
    assert exact and all(item.tier == "exact" for item in exact)
    assert candidates[0].tier == "exact"


def test_equivalents_per_accession_filter(synthetic_lookup: CohortLookup) -> None:
    """The accession filter serves per-filing classification consumers."""
    candidates = synthetic_lookup.equivalents(
        "us-gaap:AccountsPayableCurrent", accession=_ACC_B
    )
    assert candidates
    assert {item.accession for item in candidates} == {_ACC_B}
    assert {item.firm for item in candidates} == {"BBB"}


def test_equivalent_facts_flag_each_incompatibility(
    synthetic_lookup: CohortLookup,
) -> None:
    """Unit, period-kind, and fiscal failures are flagged, never dropped."""
    source = _fact(_ACC_A, "us-gaap:AccountsPayableCurrent", 100.0, "USD")
    matches = synthetic_lookup.equivalent_facts(source)
    by_pair = {}
    for item in matches:
        by_pair.setdefault((item.accession, item.qname, item.fact.unit), item)
    aligned = by_pair[(_ACC_B, "us-gaap:AccountsPayableCurrent", "USD")]
    assert aligned.compatible and aligned.fact.value == 200.0
    euros = by_pair[(_ACC_B, "us-gaap:AccountsPayableCurrent", "EUR")]
    assert not euros.compatible and euros.incompatibility == "unit"
    flow = by_pair[(_ACC_B, "us-gaap:OtherLiabilitiesCurrent", "USD")]
    assert not flow.compatible and flow.incompatibility == "period_kind"
    prior = by_pair[(_ACC_B, "us-gaap:LiabilitiesCurrent", "USD")]
    assert not prior.compatible and prior.incompatibility == "fiscal_period"
    first_incompatible = next(
        index for index, item in enumerate(matches) if not item.compatible
    )
    assert all(item.compatible for item in matches[:first_incompatible])


@pytest.fixture(scope="module")
def seed_lookup(taxonomy: DomainTaxonomy) -> CohortLookup:
    """The grounded cohort: seed registry, full concept table, one lookup."""
    entries = load_seed_cohort()
    lookup = CohortLookup(build_cohort_table(taxonomy, entries), entries)
    yield lookup
    lookup.close()


def _msft_source() -> XbrlFact:
    facts = load_seed_facts("msft_2024_10k")
    own = [
        fact
        for fact in facts
        if fact.concept_qname == "us-gaap:AccountsPayableCurrent"
        and not fact.dimensions
    ]
    return max(own, key=lambda fact: fact.instant_date or "")


def test_payables_exact_across_firms(seed_lookup: CohortLookup) -> None:
    """Payables-current pairs classify exact across firms, ranked first."""
    candidates = seed_lookup.equivalents("us-gaap:AccountsPayableCurrent")
    same = [
        item for item in candidates if item.qname == "us-gaap:AccountsPayableCurrent"
    ]
    assert len(same) >= 20
    assert all(item.tier == "exact" and item.rule == "equality" for item in same)
    assert candidates[0].qname == "us-gaap:AccountsPayableCurrent"
    assert candidates[0].tier == "exact"


def test_bare_payables_near_forms(seed_lookup: CohortLookup) -> None:
    """Bare payables: current near-specialization, accrued via-default,
    total current liabilities near-generalization on presumed geometry."""
    candidates = seed_lookup.equivalents("us-gaap:AccountsPayable")
    by_qname: dict[str, list] = {}
    for item in candidates:
        by_qname.setdefault(item.qname, []).append(item)
    current = by_qname["us-gaap:AccountsPayableCurrent"][0]
    assert current.tier == "near"
    assert current.rule == "single_modifier_difference"
    assert current.direction == "specialization"
    assert candidates[0].qname == "us-gaap:AccountsPayableCurrent"
    accrued = by_qname["us-gaap:AccruedLiabilitiesCurrent"][0]
    assert accrued.tier == "near" and accrued.via_default
    total = by_qname["us-gaap:LiabilitiesCurrent"][0]
    assert total.tier == "near" and total.direction == "generalization"


def test_incompatible_unit_specimen(seed_lookup: CohortLookup) -> None:
    """A euro-reporting firm's near candidates are flagged, not dropped."""
    matches = seed_lookup.equivalent_facts(_msft_source())
    asml = [item for item in matches if item.firm == "ASML"]
    assert asml
    assert all(not item.compatible for item in asml)
    assert all(item.incompatibility == "unit" for item in asml)
    euros = [item for item in asml if item.fact.unit == "EUR"]
    assert len(euros) >= 20
    compatible = [item for item in matches if item.compatible]
    assert compatible
    assert all(item.fact.unit == "USD" for item in compatible)
    assert all(item.fact.period_type == "instant" for item in compatible)


def test_per_accession_fact_specimen(seed_lookup: CohortLookup) -> None:
    """One filing's slice of the cohort query returns only its own facts."""
    entries = {entry.firm: entry for entry in load_seed_cohort()}
    matches = seed_lookup.equivalent_facts(
        _msft_source(), accession=entries["ASML"].accession
    )
    assert matches
    assert {item.accession for item in matches} == {entries["ASML"].accession}
    assert all(item.firm == "ASML" for item in matches)
