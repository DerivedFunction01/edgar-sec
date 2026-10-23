"""Tests pinning cohort-sourced fact sets against loaded facades."""

import json

import pyarrow.parquet as pq
import pytest

from edgar_sec.apps.client.xbrl import Xbrl
from edgar_sec.domain.identity import AccessionNumber, Cik
from edgar_sec.engine.xbrl.schema.models import (
    CalculationArc,
    FilingXbrl,
    LinkbaseBundle,
    XbrlFact,
)
from edgar_sec.engine.xbrl.solve.cohort_lookup import CohortFact, CohortFactMatch
from edgar_sec.engine.xbrl.solve.concept_table import (
    CohortEntry,
    build_cohort_table,
)
from edgar_sec.engine.xbrl.solve.query import QueryMode
from edgar_sec.engine.xbrl.storage.storage import (
    declarations_from_arrow_table,
    read_declarations_parquet,
)
from edgar_sec.engine.xbrl.taxonomy.domain import load_domain_taxonomy
from tests.engine.xbrl.solve.conftest import load_seed_cohort
from tests.support import fixture_path


def _load_bundle(folder: str) -> FilingXbrl:
    root = fixture_path(f"xbrl/seed/{folder}")
    facts = tuple(
        XbrlFact(
            accession=AccessionNumber.from_any(row["accession"]),
            concept_qname=row["concept_qname"],
            value=(
                row["numeric_value"]
                if row["numeric_value"] is not None
                else row["text_value"]
            ),
            unit=row["unit"],
            decimals=row["decimals"],
            period_type=row["period_type"],
            start_date=row["start_date"],
            end_date=row["end_date"],
            instant_date=row["instant_date"],
            dimensions=json.loads(row["dimensions_json"]),
            context_id=row["context_id"],
        )
        for row in pq.read_table(root / "facts.parquet").to_pylist()
    )
    arcs = tuple(
        CalculationArc(
            parent_qname=row["parent_qname"],
            child_qname=row["child_qname"],
            weight=row["weight"],
            order=row["order"],
            role_uri=row["role_uri"],
        )
        for row in pq.read_table(root / "calculation_arcs.parquet").to_pylist()
    )
    declarations = declarations_from_arrow_table(
        read_declarations_parquet(root / "declarations.parquet")
    )
    return FilingXbrl(
        accession=AccessionNumber("0000000000-24-000000"),
        cik=Cik(0),
        facts=facts,
        linkbases=LinkbaseBundle(calculation_arcs=arcs, declarations=declarations),
    )


@pytest.fixture(scope="module")
def cohort() -> tuple:
    """Entries plus the concept table carrying the cohort's declarations."""
    taxonomy = load_domain_taxonomy()
    entries = load_seed_cohort()
    merged: dict[str, object] = {}
    for entry in entries:
        path = entry.facts_path.parent / "declarations.parquet"
        if path.exists():
            for decl in declarations_from_arrow_table(read_declarations_parquet(path)):
                merged[decl.concept_qname] = decl
    table = build_cohort_table(taxonomy, entries, declarations=tuple(merged.values()))
    return taxonomy, entries, table


def _fact_key(fact: XbrlFact) -> tuple:
    return (
        fact.concept_qname,
        repr(fact.value),
        fact.unit,
        fact.period_type,
        fact.start_date,
        fact.end_date,
        fact.instant_date,
        json.dumps(fact.dimensions, sort_keys=True),
    )


@pytest.mark.parametrize(
    "firm,folder",
    [("MSFT", "msft_2024_10k"), ("V", "v_2024_10k"), ("ALL_2022", "all_2022_2022_10k")],
)
def test_from_cohort_agrees_with_loaded(cohort, firm: str, folder: str) -> None:
    """Verify indexed fact sets match loaded sets: count, facts, atoms."""
    taxonomy, entries, table = cohort
    entry = next(e for e in entries if e.firm == firm)
    loaded = Xbrl(_load_bundle(folder), taxonomy)
    indexed = Xbrl.from_cohort(table, entries, entry.accession)
    assert len(indexed.facts) == len(loaded.facts)
    assert sorted(_fact_key(f) for f in indexed.facts) == sorted(
        _fact_key(f) for f in loaded.facts
    )
    for qname, record in loaded.facts.records.items():
        other = indexed.facts.records[qname]
        assert (other.atom.head, other.atom.modifiers) == (
            record.atom.head,
            record.atom.modifiers,
        )


def test_from_cohort_query_battery_matches_loaded(cohort) -> None:
    """Verify census-style queries answer identically from indexed sets."""
    taxonomy, entries, table = cohort
    entry = next(e for e in entries if e.firm == "MSFT")
    loaded = Xbrl(_load_bundle("msft_2024_10k"), taxonomy)
    indexed = Xbrl.from_cohort(table, entries, entry.accession)
    for term in ("revenue", "cfo", "us-gaap:Assets", "Net Income"):
        for mode in (QueryMode.REPORTED_ONLY, QueryMode.VERIFY_DERIVATION):
            want = loaded.query(term, mode=mode, fiscal_year=2024)
            got = indexed.query(term, mode=mode, fiscal_year=2024)
            assert (got.status, got.value) == (want.status, want.value)


def test_from_cohort_carries_the_filings_evidence_record(cohort) -> None:
    """Verify a cohort facade carries its own filing's evidence record."""
    taxonomy, entries, table = cohort
    entry = next(e for e in entries if e.firm == "AAPL")
    indexed = Xbrl.from_cohort(table, entries, entry.accession)
    record = indexed.evidence
    assert record is not None
    assert record.accession == entry.accession and record.firm == "AAPL"
    payables = record.entry("us-gaap:AccountsPayableCurrent")
    assert payables is not None
    assert payables.placement_horizon == "M_CURRENT"
    assert payables.attested_placed
    loaded = Xbrl(_load_bundle("aapl_2024_10k"), taxonomy)
    assert loaded.evidence is None


def test_from_cohort_unknown_accession_raises(cohort) -> None:
    """Verify an accession outside the cohort entries is refused."""
    _taxonomy, entries, table = cohort
    with pytest.raises(ValueError, match="not among cohort entries"):
        Xbrl.from_cohort(table, entries, "0000000000-00-000000")


def test_from_lookup_records_carry_tier_and_rule(cohort) -> None:
    """Verify lookup-sourced records carry tier/rule and project facts."""
    taxonomy, entries, table = cohort
    entry = next(e for e in entries if e.firm == "MSFT")
    record = table.record("us-gaap:NetCashProvidedByUsedInOperatingActivities")
    match = CohortFactMatch(
        accession=entry.accession,
        firm="MSFT",
        qname=record.qname,
        atom=record.atom,
        tier="EXACT",
        rule="identity",
        direction="SAME",
        via_default=False,
        fact=CohortFact(
            accession=entry.accession,
            qname=record.qname,
            value=118_548_000_000.0,
            unit="USD",
            period_type="duration",
            start_date="2023-07-01",
            end_date="2024-06-30",
        ),
        compatible=True,
    )
    facade = Xbrl.from_lookup(table, [match], entry.accession)
    assert len(facade.facts) == 1
    fact = facade.facts[0]
    assert fact.value == 118_548_000_000.0
    assert fact.dimensions == {}  # display projection: no dimensions
    display = facade.facts.records[record.qname]
    assert display.tier == "EXACT"
    assert display.rule == "identity"
    assert display.atom == record.atom
    assert display.residual_mass == (record.residual_intent, record.residual_total)


def test_from_lookup_filters_other_accessions(cohort) -> None:
    """Verify from_lookup keeps only the requested accession's matches."""
    _taxonomy, entries, table = cohort
    entry = next(e for e in entries if e.firm == "MSFT")
    record = table.record("us-gaap:Assets")

    def make_match(accession: str) -> CohortFactMatch:
        return CohortFactMatch(
            accession=accession,
            firm="X",
            qname=record.qname,
            atom=record.atom,
            tier="EXACT",
            rule="identity",
            direction="SAME",
            via_default=False,
            fact=CohortFact(
                accession=accession,
                qname=record.qname,
                value=1.0,
                unit="USD",
                period_type="instant",
                instant_date="2024-06-30",
            ),
            compatible=True,
        )

    facade = Xbrl.from_lookup(
        table,
        [make_match(entry.accession), make_match("9999999999-99-999999")],
        entry.accession,
    )
    assert len(facade.facts) == 1
