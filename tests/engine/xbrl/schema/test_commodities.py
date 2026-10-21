"""Commodity graph: IS_A-only category closure and attested firm links."""

from __future__ import annotations

import json

import pyarrow.parquet as pq

from edgar_sec.engine.xbrl.paths import resolve_xbrl_paths
from edgar_sec.engine.xbrl.schema.commodities import CommodityGraph
from tests.support import fixture_path


def _graph() -> CommodityGraph:
    """Load the seeded commodity graph from taxonomy data."""
    return CommodityGraph.load_json(resolve_xbrl_paths().default_commodity_graph_path)


def test_energy_expansion_lands_groups_and_excludes_corn() -> None:
    """D7: energy expands to coal/oil/gas/electricity, never corn."""
    graph = _graph()

    energy = graph.expand("ENERGY")
    assert {"COAL", "OIL", "GAS", "ELECTRICITY"} <= energy
    assert {"crude_oil", "natural_gas", "jet_fuel", "diesel"} <= energy
    assert "corn" not in energy
    assert "CROPS" not in energy


def test_feedstock_edge_is_never_traversed() -> None:
    """Corn is ethanol's feedstock, yet crops expansion excludes ethanol."""
    graph = _graph()

    assert "ethanol" in graph.expand("ENERGY")
    assert graph.expand("CROPS") == frozenset({"CROPS", "corn"})


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


def test_two_firms_producing_gold_unify() -> None:
    """Spot proof: FCX and NEM share the gold instrument as producers."""
    graph = _graph()

    producers = {link.firm for link in graph.links_for("gold", "PRODUCES")}
    assert producers == {"FCX", "NEM"}
    assert {link.firm for link in graph.links_for("natural_gas", "CONSUMES")} == {"CF"}
