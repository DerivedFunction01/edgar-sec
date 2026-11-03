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
from tests.engine.xbrl.solve.conftest import (
    load_seed_cohort,
    load_seed_facts,
    seed_folder,
)

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


_PARENT_SCOPE = {"srt:ConsolidatedEntitiesAxis": "srt:ParentCompanyMember"}


def _scoped_fact(accession: str, value: float, dimensions: dict[str, str]) -> XbrlFact:
    return XbrlFact(
        accession=AccessionNumber.from_any(accession),
        concept_qname="us-gaap:AccountsPayableCurrent",
        value=value,
        unit="USD",
        period_type="instant",
        instant_date="2024-12-31",
        dimensions=dimensions,
    )


@pytest.fixture()
def scoped_lookup(taxonomy: DomainTaxonomy, tmp_path: Path) -> CohortLookup:
    """Two filings carrying payables in consolidated and parent scopes."""
    path_a = tmp_path / "aaa" / "facts.parquet"
    path_b = tmp_path / "bbb" / "facts.parquet"
    write_facts_parquet(
        [
            _scoped_fact(_ACC_A, 100.0, {}),
            _scoped_fact(_ACC_A, 90.0, _PARENT_SCOPE),
        ],
        path_a,
    )
    write_facts_parquet(
        [
            _scoped_fact(_ACC_B, 200.0, {}),
            _scoped_fact(_ACC_B, 180.0, _PARENT_SCOPE),
        ],
        path_b,
    )
    entries = (
        CohortEntry(accession=_ACC_A, facts_path=path_a, firm="AAA"),
        CohortEntry(accession=_ACC_B, facts_path=path_b, firm="BBB"),
    )
    lookup = CohortLookup(build_cohort_table(taxonomy, entries), entries)
    yield lookup
    lookup.close()


def test_equivalent_facts_flag_scope_mismatch(scoped_lookup: CohortLookup) -> None:
    """A candidate under another dimension scope is flagged, never dropped."""
    source = _scoped_fact(_ACC_A, 100.0, {})
    matches = [
        item for item in scoped_lookup.equivalent_facts(source) if item.firm == "BBB"
    ]
    by_value = {item.fact.value: item for item in matches}
    assert by_value[200.0].compatible
    assert not by_value[180.0].compatible
    assert by_value[180.0].incompatibility == "dimensions"
    assert by_value[180.0].fact.dimensions == _PARENT_SCOPE


def test_equivalent_facts_exact_within_scope(scoped_lookup: CohortLookup) -> None:
    """Same-scope candidates stay compatible; the consolidated row flips."""
    source = _scoped_fact(_ACC_A, 90.0, _PARENT_SCOPE)
    matches = [
        item for item in scoped_lookup.equivalent_facts(source) if item.firm == "BBB"
    ]
    by_value = {item.fact.value: item for item in matches}
    assert by_value[180.0].compatible and by_value[180.0].tier == "exact"
    assert not by_value[200.0].compatible
    assert by_value[200.0].incompatibility == "dimensions"


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
    # Wave D + Step 7 adjudication: DUK's textblocks and CVX's affiliated-
    # companies payables decompose onto the bare atom exactly; they head it.
    assert {item.qname for item in candidates[:3]} == {
        "cvx:AccountsPayableDueToAffiliatedCompanies",
        "duk:AccountsPayablePolicyPolicyTextBlock",
        "duk:ScheduleOfAccountsPayableAndSupplierInvoicesSoldTableTextBlock",
    }
    assert all(
        item.tier == "exact" and item.rule == "equality" for item in candidates[:3]
    )
    first_near = next(item for item in candidates if item.tier == "near")
    assert first_near.qname == "us-gaap:AccountsPayableCurrent"
    accrued = by_qname["us-gaap:AccruedLiabilitiesCurrent"][0]
    assert accrued.tier == "near" and accrued.via_default
    total = by_qname["us-gaap:LiabilitiesCurrent"][0]
    assert total.tier == "near" and total.direction == "generalization"


def test_bare_head_crowding_demoted_on_seed_cohort(
    seed_lookup: CohortLookup,
) -> None:
    """F-WS4S3-1: bare-atom pairs are NEAR; EXACT is same-qname only here."""
    candidates = seed_lookup.equivalents("us-gaap:Assets")
    exact = [item for item in candidates if item.tier == "exact"]
    assert exact and all(item.qname == "us-gaap:Assets" for item in exact)
    assert all(item.rule == "equality" for item in exact)
    crowded = [item for item in candidates if item.qname == "us-gaap:OtherReceivables"]
    assert crowded
    assert all(
        item.tier == "near" and item.rule == "bare_head_equality" for item in crowded
    )


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


_JPM_PARENT_ALONE = (
    "jpm:NetIncomeLossAttributabletoParentAloneExcludingDividendsand"
    "IncomefromSubsidiariesandAffiliates"
)


def _jpm_fact(qname: str, dimensions: dict[str, str]) -> XbrlFact:
    own = [
        fact
        for fact in load_seed_facts(seed_folder("JPM"))
        if fact.concept_qname == qname and dict(fact.dimensions) == dimensions
    ]
    return max(own, key=lambda fact: fact.end_date or "")


def test_parent_alone_slice_flagged_for_consolidated_source(
    seed_lookup: CohortLookup,
) -> None:
    """JPM's parent-alone extension never serves as consolidated net income."""
    source = _jpm_fact("us-gaap:NetIncomeLoss", {})
    assert source.value == 58_471_000_000.0
    matches = seed_lookup.equivalent_facts(source)
    extension = [item for item in matches if item.qname == _JPM_PARENT_ALONE]
    assert extension
    assert all(not item.compatible for item in extension)
    current = [item for item in extension if item.fact.end_date == "2024-12-31"]
    assert len(current) == 1
    assert current[0].incompatibility == "dimensions"
    assert current[0].fact.value == -14_310_000_000.0


def test_parent_alone_pair_exact_within_scope(seed_lookup: CohortLookup) -> None:
    """Scoped to parent-alone, the JPM extension matches BAC's standard fact."""
    source = _jpm_fact(_JPM_PARENT_ALONE, _PARENT_SCOPE)
    matches = seed_lookup.equivalent_facts(source)
    bac = [
        item
        for item in matches
        if item.firm == "BAC"
        and item.qname == "us-gaap:NetIncomeLoss"
        and item.fact.end_date == "2024-12-31"
        and dict(item.fact.dimensions) == _PARENT_SCOPE
    ]
    assert bac
    assert all(item.compatible and item.tier == "exact" for item in bac)
    assert all(item.fact.value == 27_132_000_000.0 for item in bac)


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


def test_equivalent_facts_flag_superseded_originals(
    taxonomy: DomainTaxonomy, tmp_path: Path
) -> None:
    """A restated original fact is flagged and ranked behind its amendment."""
    from edgar_sec.engine.xbrl.solve.scoping import FilingRef, build_lineages

    path_a = tmp_path / "orig" / "facts.parquet"
    path_b = tmp_path / "amend" / "facts.parquet"
    source = _fact(_ACC_A, "us-gaap:AccountsPayableCurrent", 100.0, "USD")
    write_facts_parquet([source], path_a)
    write_facts_parquet(
        [_fact(_ACC_B, "us-gaap:AccountsPayableCurrent", 200.0, "USD")], path_b
    )
    entries = (
        CohortEntry(accession=_ACC_A, facts_path=path_a, firm="AAA"),
        CohortEntry(accession=_ACC_B, facts_path=path_b, firm="AAA"),
    )
    table = build_cohort_table(taxonomy, entries)
    lineages = build_lineages(
        [
            FilingRef(_ACC_A, "1", "10-K", "2024-12-31", "2025-03-01"),
            FilingRef(_ACC_B, "1", "10-K/A", "2024-12-31", "2025-06-01"),
        ]
    )
    lookup = CohortLookup(table, entries, lineages)
    try:
        matches = lookup.equivalent_facts(source)
    finally:
        lookup.close()
    by_accession = {match.accession: match for match in matches}
    assert by_accession[_ACC_A].superseded_by == _ACC_B
    assert by_accession[_ACC_B].superseded_by == ""
    assert matches[0].accession == _ACC_B


def test_pair_set_holds_over_the_seed_cohort(seed_lookup: CohortLookup) -> None:
    """Every seeded cross-firm pair holds at its expected tier, live."""
    from edgar_sec.engine.xbrl.review.benchmark import PAIR_SET, evaluate_pairs

    source_facts = {}
    for spec in PAIR_SET:
        if not spec.source_firm:
            continue
        facts = load_seed_facts(seed_folder(spec.source_firm))
        scope = dict(spec.source_scope)
        own = [
            fact
            for fact in facts
            if fact.concept_qname == spec.target and dict(fact.dimensions) == scope
        ]
        source_facts[(spec.source_firm, spec.target)] = max(
            own,
            key=lambda fact: fact.end_date or fact.instant_date or "",
        )
    report = evaluate_pairs(seed_lookup, PAIR_SET, source_facts)
    assert report.failures == ()
    assert report.passed == report.total == len(PAIR_SET)


@pytest.fixture()
def dialect_lookup(taxonomy: DomainTaxonomy, tmp_path: Path) -> CohortLookup:
    """Two filings stating one acquisition in the two naming dialects."""
    path_a = tmp_path / "aaa" / "facts.parquet"
    path_b = tmp_path / "bbb" / "facts.parquet"
    write_facts_parquet(
        [
            _fact(
                _ACC_A,
                "us-gaap:PaymentsToAcquirePropertyPlantAndEquipment",
                100.0,
                "USD",
                period_type="duration",
                instant_date=None,
                start_date="2024-01-01",
                end_date="2024-12-31",
            )
        ],
        path_a,
    )
    write_facts_parquet(
        [
            _fact(
                _ACC_B,
                "ifrs-full:PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities",
                90.0,
                "USD",
                period_type="duration",
                instant_date=None,
                start_date="2024-01-01",
                end_date="2024-12-31",
            )
        ],
        path_b,
    )
    entries = (
        CohortEntry(accession=_ACC_A, facts_path=path_a, firm="AAA"),
        CohortEntry(accession=_ACC_B, facts_path=path_b, firm="BBB"),
    )
    lookup = CohortLookup(build_cohort_table(taxonomy, entries), entries)
    yield lookup
    lookup.close()


def test_equivalents_cross_the_dialect_bridge(dialect_lookup: CohortLookup) -> None:
    """A payments-dialect target reaches the purchase-dialect filing."""
    candidates = dialect_lookup.equivalents(
        "us-gaap:PaymentsToAcquirePropertyPlantAndEquipment"
    )
    bridged = [
        item
        for item in candidates
        if item.qname.startswith("ifrs-full:PurchaseOfPropertyPlantAndEquipment")
    ]
    assert len(bridged) == 1
    assert bridged[0].accession == _ACC_B
    assert bridged[0].tier == "near"
    assert bridged[0].rule == "dialect_bridge"
    assert bridged[0].via_bridge is True
