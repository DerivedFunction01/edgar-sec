"""Equivalent-scan pooling: head grouping and the population-wide year set."""

from edgar_sec.apps.client.equivalence_scan import (
    cached_default_years,
    default_year_set,
    facts_by_head,
)
from edgar_sec.apps.client.facts import DisplayRecord, XbrlFactSet
from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.engine.xbrl.schema.atoms import Atom
from edgar_sec.engine.xbrl.schema.models import XbrlFact
from edgar_sec.engine.xbrl.taxonomy.domain import load_domain_taxonomy

_ACCESSION = AccessionNumber("0000000000-24-000000")
_ANNUAL_ONLY = frozenset({"ANNUAL"})
_INTERIM = frozenset({"YTD_3Q", "YTD_2Q", "QUARTER"})


def _fact(qname: str, **kwargs) -> XbrlFact:
    return XbrlFact(accession=_ACCESSION, concept_qname=qname, **kwargs)


def _record(qname: str, head: str) -> DisplayRecord:
    atom = Atom(head)
    return DisplayRecord(qname=qname, atom=atom, presumed_atom=atom)


def _fact_set(facts, records) -> XbrlFactSet:
    return XbrlFactSet(facts, load_domain_taxonomy(), records=records)


def test_facts_by_head_groups_by_record_head_in_population_order() -> None:
    """Groups carry the scan's own population and order; record-less under None."""
    facts = (
        _fact("us-gaap:Assets", value=1.0),
        _fact("us-gaap:Revenues", value=2.0),
        _fact("us-gaap:AssetsCurrent", value=3.0),
        _fact("ex:Untokenized", value=4.0),
    )
    records = {
        "us-gaap:Assets": _record("us-gaap:Assets", "H_ASSET"),
        "us-gaap:AssetsCurrent": _record("us-gaap:AssetsCurrent", "H_ASSET"),
        "us-gaap:Revenues": _record("us-gaap:Revenues", "H_REVENUE"),
    }
    index = facts_by_head(_fact_set(facts, records))
    assert index["H_ASSET"] == [facts[0], facts[2]]
    assert index["H_REVENUE"] == [facts[1]]
    assert index[None] == [facts[3]]


def test_default_year_set_spans_the_population_per_class_set() -> None:
    """Years come from coarse bucket creation, not from any head's facts."""
    facts = (
        _fact(
            "us-gaap:Revenues",
            value=1.0,
            unit="USD",
            start_date="2024-01-01",
            end_date="2024-12-31",
        ),
        _fact(
            "us-gaap:Revenues",
            value=2.0,
            unit="USD",
            start_date="2022-01-01",
            end_date="2022-03-31",
        ),
        _fact(
            "us-gaap:Assets",
            value=3.0,
            unit="USD",
            period_type="instant",
            instant_date="2023-12-31",
        ),
        _fact(
            "us-gaap:Assets",
            value=4.0,
            unit="USD",
            start_date="2025-01-01",
            end_date="2025-12-31",
            dimensions={"us-gaap:Axis": "us-gaap:Member"},
        ),
        _fact(
            "us-gaap:Assets",
            value=5.0,
            unit="pure",
            start_date="2025-01-01",
            end_date="2025-12-31",
        ),
        _fact(
            "us-gaap:Assets",
            value="n/a",
            unit="USD",
            start_date="2025-01-01",
            end_date="2025-12-31",
        ),
    )
    fact_set = _fact_set(facts, {})
    assert default_year_set(fact_set, _ANNUAL_ONLY) == frozenset({"2024", "2023"})
    assert default_year_set(fact_set, _INTERIM) == frozenset({"2022", "2023"})


def test_cached_default_years_computes_once_per_class_set() -> None:
    """A second call for a class-set returns the cached set object itself."""
    facts = (
        _fact(
            "us-gaap:Assets",
            value=1.0,
            unit="USD",
            period_type="instant",
            instant_date="2024-12-31",
        ),
    )
    fact_set = _fact_set(facts, {})
    cache: dict[frozenset[str], frozenset[str]] = {}
    first = cached_default_years(cache, fact_set, _ANNUAL_ONLY)
    assert first == frozenset({"2024"})
    assert cached_default_years(cache, fact_set, _ANNUAL_ONLY) is first
    assert cached_default_years(cache, fact_set, _INTERIM) == frozenset({"2024"})
    assert len(cache) == 2
