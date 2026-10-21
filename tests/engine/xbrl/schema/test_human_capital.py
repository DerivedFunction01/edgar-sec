"""Human capital graph: workforce nodes with pattern-derived firm links."""

from __future__ import annotations

import json

import pyarrow.parquet as pq

from edgar_sec.engine.xbrl.normalize.decomposer import (
    decompose_concept,
    split_camel_case,
)
from edgar_sec.engine.xbrl.paths import resolve_xbrl_paths
from edgar_sec.engine.xbrl.schema.commodities import CommodityGraph, FirmCommodityLink
from edgar_sec.engine.xbrl.taxonomy.domain import load_domain_taxonomy
from tests.support import fixture_path

ATTESTED_LINKS = (
    ("DAL", "HEADCOUNT", "MEASURES", ("dei:EntityNumberOfEmployees",)),
    ("T", "HEADCOUNT", "MEASURES", ("dei:EntityNumberOfEmployees",)),
    (
        "ASML",
        "HEADCOUNT",
        "MEASURES",
        (
            "dei:EntityNumberOfEmployees",
            "asml:AverageNumberOfPayrollEmployeesEmployed",
        ),
    ),
    (
        "JNJ",
        "HEADCOUNT",
        "MEASURES",
        ("jnj:NumberOfEmployeesEngagedInCompanyActivitiesWorldwide",),
    ),
    (
        "DAL",
        "UNION_EXPOSURE",
        "MEASURES",
        (
            "dal:PercentageOfEmployeesRepresentedByUnionsUnderCollectiveBargainingAgreements",
        ),
    ),
    (
        "DAL",
        "UNION_EXPOSURE",
        "NARRATIVE",
        ("dal:DomesticEmployeeGroupsRepresentedByUnionsTableTextBlock",),
    ),
    (
        "ASML",
        "UNION_EXPOSURE",
        "MEASURES",
        ("asml:MultiemployerPlanCollectiveBargainingArrangementNumberOfEmployees",),
    ),
    (
        "DE",
        "UNION_EXPOSURE",
        "MEASURES",
        (
            "de:CollectiveBargainingArrangementNumberOfFacilities",
            "de:CollectiveBargainingArrangementTermOfContract",
        ),
    ),
    (
        "TSN",
        "UNION_EXPOSURE",
        "MEASURES",
        (
            "us-gaap:MultiemployerPlanPensionInsignificantCollectiveBargainingArrangementExpirationDate",
        ),
    ),
)


def _graph() -> CommodityGraph:
    """Load the human capital graph (shared domain-graph format)."""
    return CommodityGraph.load_json(
        resolve_xbrl_paths().default_human_capital_graph_path
    )


def _derive_all(graph: CommodityGraph) -> tuple[FirmCommodityLink, ...]:
    """Derive links for every seed firm from its bundle concepts."""
    taxonomy = load_domain_taxonomy()
    lexicon = taxonomy.token_lexicon
    assert lexicon is not None

    def classify(qname: str):
        atom = decompose_concept(qname, lexicon)[0]
        tokens = tuple(t.lower() for t in split_camel_case(qname.split(":")[-1]))
        return atom, tokens

    registry = json.loads(
        fixture_path("xbrl/seed/fixture_source_registry.json").read_text()
    )
    derived: list[FirmCommodityLink] = []
    for item in registry["bundles"]:
        facts = pq.read_table(
            fixture_path(f"xbrl/seed/{item['folder']}/facts.parquet"),
            columns=["concept_qname"],
        )
        concepts = sorted(set(facts.column("concept_qname").to_pylist()))
        derived.extend(graph.derive_links(item["firm"], concepts, classify))
    return tuple(derived)


def test_workforce_expansion_and_demographic_seed() -> None:
    """Workforce expands to its measures; demographics stay unlinked."""
    graph = _graph()

    assert graph.expand("WORKFORCE") == frozenset(
        {"WORKFORCE", "HEADCOUNT", "UNION_EXPOSURE"}
    )
    derived = _derive_all(graph)
    assert {link.instrument for link in derived} <= {"HEADCOUNT", "UNION_EXPOSURE"}


def test_derived_links_reproduce_attested_set() -> None:
    """Derivation over the seed bundles reproduces the attested 9 links."""
    derived = _derive_all(_graph())

    derived_keys = {(link.firm, link.instrument, link.relation) for link in derived}
    attested_keys = {(firm, inst, rel) for firm, inst, rel, _ in ATTESTED_LINKS}
    assert derived_keys == attested_keys
    by_key = {(link.firm, link.instrument, link.relation): link for link in derived}
    for firm, instrument, relation, concepts in ATTESTED_LINKS:
        link = by_key[(firm, instrument, relation)]
        assert set(concepts) <= set(link.concepts)


def test_union_exposure_is_attested_beyond_airlines() -> None:
    """Union links span DAL, ASML, DE, TSN; narrative is a distinct relation."""
    derived = _derive_all(_graph())

    measured = {
        link.firm
        for link in derived
        if link.instrument == "UNION_EXPOSURE" and link.relation == "MEASURES"
    }
    assert measured == {"DAL", "ASML", "DE", "TSN"}
    narrative = {
        link.firm
        for link in derived
        if link.instrument == "UNION_EXPOSURE" and link.relation == "NARRATIVE"
    }
    assert narrative == {"DAL"}
