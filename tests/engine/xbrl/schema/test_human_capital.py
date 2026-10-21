"""Human capital graph: workforce nodes with attested firm links only."""

from __future__ import annotations

import json

import pyarrow.parquet as pq

from edgar_sec.engine.xbrl.paths import resolve_xbrl_paths
from edgar_sec.engine.xbrl.schema.commodities import CommodityGraph
from tests.support import fixture_path


def _graph() -> CommodityGraph:
    """Load the human capital graph (shared domain-graph format)."""
    return CommodityGraph.load_json(
        resolve_xbrl_paths().default_human_capital_graph_path
    )


def test_workforce_expansion_and_demographic_seed() -> None:
    """Workforce expands to its measures; demographics stay unlinked."""
    graph = _graph()

    assert graph.expand("WORKFORCE") == frozenset(
        {"WORKFORCE", "HEADCOUNT", "UNION_EXPOSURE"}
    )
    assert graph.links_for("DEMOGRAPHIC_SEGMENT") == ()


def test_every_link_cites_a_corpus_concept() -> None:
    """Each seeded link's concepts exist in that firm's seed bundle."""
    graph = _graph()
    registry = json.loads(
        fixture_path("xbrl/seed/fixture_source_registry.json").read_text()
    )
    folders = {item["firm"]: item["folder"] for item in registry["bundles"]}
    concept_cache: dict[str, set[str]] = {}
    for link in graph.links:
        assert link.concepts
        if link.firm not in concept_cache:
            facts = pq.read_table(
                fixture_path(f"xbrl/seed/{folders[link.firm]}/facts.parquet"),
                columns=["concept_qname"],
            )
            concept_cache[link.firm] = set(facts.column("concept_qname").to_pylist())
        for concept in link.concepts:
            assert concept in concept_cache[link.firm]


def test_union_exposure_is_attested_beyond_airlines() -> None:
    """Union links span DAL, ASML, DE, TSN; narrative is a distinct relation."""
    graph = _graph()

    measured = {link.firm for link in graph.links_for("UNION_EXPOSURE", "MEASURES")}
    assert measured == {"DAL", "ASML", "DE", "TSN"}
    narrative = {link.firm for link in graph.links_for("UNION_EXPOSURE", "NARRATIVE")}
    assert narrative == {"DAL"}
