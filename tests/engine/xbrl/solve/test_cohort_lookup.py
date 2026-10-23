"""Tests for the DuckDB-direct cohort lookup and its grounded specimens."""

from __future__ import annotations

from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
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
_ACC_C = "0000000003-24-000003"
_ROLE = "http://example.com/role/BALANCESHEET"


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


def _calc_arcs(path: Path, parent: str, child: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(
        pa.Table.from_pylist(
            [
                {
                    "parent_qname": parent,
                    "child_qname": child,
                    "weight": 1.0,
                    "order": 1.0,
                    "role_uri": _ROLE,
                }
            ]
        ),
        path,
    )


@pytest.fixture()
def filing_local_lookup(taxonomy: DomainTaxonomy, tmp_path: Path) -> CohortLookup:
    """Two filings whose bare payables sit under opposite horizon totals."""
    path_b = tmp_path / "bbb" / "facts.parquet"
    path_c = tmp_path / "ccc" / "facts.parquet"
    write_facts_parquet(
        [
            _fact(_ACC_B, "us-gaap:AccountsPayable", 100.0, "USD"),
            _fact(_ACC_B, "us-gaap:AccruedLiabilitiesCurrent", 50.0, "USD"),
            _fact(_ACC_B, "us-gaap:LiabilitiesCurrent", 900.0, "USD"),
        ],
        path_b,
    )
    _calc_arcs(
        path_b.parent / "calculation_arcs.parquet",
        "us-gaap:LiabilitiesCurrent",
        "us-gaap:AccountsPayable",
    )
    write_facts_parquet(
        [
            _fact(_ACC_C, "us-gaap:AccountsPayable", 100.0, "USD"),
            _fact(_ACC_C, "us-gaap:AccruedLiabilitiesCurrent", 50.0, "USD"),
            _fact(_ACC_C, "us-gaap:LiabilitiesNoncurrent", 900.0, "USD"),
        ],
        path_c,
    )
    _calc_arcs(
        path_c.parent / "calculation_arcs.parquet",
        "us-gaap:LiabilitiesNoncurrent",
        "us-gaap:AccountsPayable",
    )
    entries = (
        CohortEntry(accession=_ACC_B, facts_path=path_b, firm="BBB"),
        CohortEntry(accession=_ACC_C, facts_path=path_c, firm="CCC"),
    )
    lookup = CohortLookup(build_cohort_table(taxonomy, entries), entries)
    yield lookup
    lookup.close()


def test_candidate_presumed_under_its_own_filing(
    filing_local_lookup: CohortLookup,
) -> None:
    """B's payables read current from B's placement; C's noncurrent is absent."""
    candidates = filing_local_lookup.equivalents("us-gaap:AccruedLiabilitiesCurrent")
    by_pair = {(item.accession, item.qname): item for item in candidates}
    placed = by_pair[(_ACC_B, "us-gaap:AccountsPayable")]
    assert placed.tier == "near" and placed.rule == "via_filing_local"
    assert placed.via_filing_local and not placed.via_default
    assert (_ACC_C, "us-gaap:AccountsPayable") not in by_pair
    order = [(item.accession, item.qname) for item in candidates if item.tier == "near"]
    assert order.index((_ACC_B, "us-gaap:AccountsPayable")) > order.index(
        (_ACC_B, "us-gaap:LiabilitiesCurrent")
    )


def test_target_presumed_only_under_query_accession(
    filing_local_lookup: CohortLookup,
) -> None:
    """Unscoped: target via default. Scoped to B: via B. Scoped to C: no match."""
    unscoped = {
        (item.accession, item.qname): item
        for item in filing_local_lookup.equivalents("us-gaap:AccountsPayable")
    }
    accrued_b = unscoped[(_ACC_B, "us-gaap:AccruedLiabilitiesCurrent")]
    assert accrued_b.via_default and accrued_b.rule == "via_default"
    scoped_b = filing_local_lookup.equivalents(
        "us-gaap:AccountsPayable", accession=_ACC_B
    )
    accrued = [i for i in scoped_b if i.qname == "us-gaap:AccruedLiabilitiesCurrent"]
    assert len(accrued) == 1
    assert accrued[0].via_filing_local and accrued[0].rule == "via_filing_local"
    assert not accrued[0].via_default
    scoped_c = filing_local_lookup.equivalents(
        "us-gaap:AccountsPayable", accession=_ACC_C
    )
    assert all(item.qname != "us-gaap:AccruedLiabilitiesCurrent" for item in scoped_c)
    assert any(
        item.qname == "us-gaap:AccountsPayable" and item.tier == "exact"
        for item in scoped_c
    )


def test_equivalent_facts_carry_via_filing_local(
    filing_local_lookup: CohortLookup,
) -> None:
    """Fact matches expose the filing-local flag of their (filing, concept)."""
    source = _fact(_ACC_A, "us-gaap:AccruedLiabilitiesCurrent", 10.0, "USD")
    matches = filing_local_lookup.equivalent_facts(source)
    payables = {
        item.accession: item
        for item in matches
        if item.qname == "us-gaap:AccountsPayable"
    }
    assert payables[_ACC_B].via_filing_local and payables[_ACC_B].compatible
    assert _ACC_C not in payables


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
    # Wave D adjudication (WS2 batch log): DUK's two payables textblocks
    # decompose onto the bare atom exactly, so they head the pool.
    assert {candidates[0].qname, candidates[1].qname} == {
        "duk:AccountsPayablePolicyPolicyTextBlock",
        "duk:ScheduleOfAccountsPayableAndSupplierInvoicesSoldTableTextBlock",
    }
    assert all(
        item.tier == "exact" and item.rule == "equality" for item in candidates[:2]
    )
    first_near = next(item for item in candidates if item.tier == "near")
    assert first_near.qname == "us-gaap:AccountsPayableCurrent"
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


def test_seed_filing_local_specimen(seed_lookup: CohortLookup) -> None:
    """APD goodwill: name silent, APD placement states noncurrent."""
    candidates = seed_lookup.equivalents("us-gaap:AssetsNoncurrent")
    apd = [
        item
        for item in candidates
        if item.firm == "APD" and item.qname == "us-gaap:Goodwill"
    ]
    assert len(apd) == 1
    assert apd[0].tier == "near" and apd[0].rule == "via_filing_local"
    assert apd[0].via_filing_local and not apd[0].via_default
    assert apd[0].modifier_distance == 1


def test_pair_set_holds_over_the_seed_cohort(seed_lookup: CohortLookup) -> None:
    """Every seeded cross-firm pair holds at its expected tier, live."""
    from edgar_sec.engine.xbrl.review.benchmark import PAIR_SET, evaluate_pairs

    source_facts = {("MSFT", "us-gaap:AccountsPayableCurrent"): _msft_source()}
    report = evaluate_pairs(seed_lookup, PAIR_SET, source_facts)
    assert report.failures == ()
    assert report.passed == report.total == len(PAIR_SET)
