"""Commodity graph: IS_A-only closure and pattern-derived firm links."""

from __future__ import annotations

import pyarrow.parquet as pq

from edgar_sec.engine.xbrl.normalize.decomposer import (
    decompose_concept,
    split_camel_case,
)
from edgar_sec.engine.xbrl.paths import resolve_xbrl_paths
from edgar_sec.engine.xbrl.schema.commodities import CommodityGraph, FirmCommodityLink
from edgar_sec.engine.xbrl.taxonomy.domain import load_domain_taxonomy
from tests.support import bundle_dir, corpus_source_bundles

ATTESTED_LINKS = (
    ("XOM", "crude_oil", "CONSUMES", ("xom:CrudeOilAndProductPurchases",)),
    ("XOM", "refined_products", "CONSUMES", ("xom:CrudeOilAndProductPurchases",)),
    ("XOM", "natural_gas", "EXPOSED_TO", ("xom:NaturalGasAndOtherInventory",)),
    (
        "FCX",
        "copper",
        "PRODUCES",
        (
            "fcx:EstimatedRecoverableProvenAndProbableCopperReservesInMillStockpiles",
            "fcx:ExportDutiesCopperConcentrate",
        ),
    ),
    ("FCX", "gold", "PRODUCES", ("fcx:SaleOfGold",)),
    ("NEM", "gold", "PRODUCES", ("nem:GoldDorePurityMarketStandard",)),
    ("ADM", "corn", "CONSUMES", ("adm:CornProcessedPerMonth",)),
    (
        "CF",
        "natural_gas",
        "CONSUMES",
        (
            "cf:CostOilAndGasIncludingImpactOfRealizedDerivatives",
            "us-gaap:GasPurchasePayableCurrent",
        ),
    ),
    (
        "CF",
        "nitrogen_fertilizer",
        "PRODUCES",
        ("cf:NumberofNitrogenFertilizerManufacturingFacilitiesNorthAmerica",),
    ),
)


def _graph() -> CommodityGraph:
    """Load the seeded commodity graph from taxonomy data."""
    return CommodityGraph.load_json(resolve_xbrl_paths().default_commodity_graph_path)


def _derive_all(graph: CommodityGraph) -> tuple[FirmCommodityLink, ...]:
    """Derive links for every seed firm from its bundle concepts."""
    taxonomy = load_domain_taxonomy()
    lexicon = taxonomy.token_lexicon
    assert lexicon is not None

    def classify(qname: str):
        atom = decompose_concept(qname, lexicon)[0]
        tokens = tuple(t.lower() for t in split_camel_case(qname.split(":")[-1]))
        return atom, tokens

    derived: list[FirmCommodityLink] = []
    for item in corpus_source_bundles():
        facts = pq.read_table(
            bundle_dir(item["folder"]) / "facts.parquet",
            columns=["concept_qname"],
        )
        concepts = sorted(set(facts.column("concept_qname").to_pylist()))
        derived.extend(graph.derive_links(item["firm"], concepts, classify))
    return tuple(derived)


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
    crops = graph.expand("CROPS")
    assert "ethanol" not in crops
    assert {"corn", "soybeans", "GRAINS_OILSEEDS"} <= crops


def test_metals_expansion_includes_base_precious_battery() -> None:
    """Metals expands to base, precious, and battery metal groups."""
    graph = _graph()

    metals = graph.expand("METALS")
    assert {"BASE_METALS", "PRECIOUS_METALS", "BATTERY_METALS"} <= metals
    assert {"gold", "silver", "copper", "aluminum", "lithium"} <= metals


def test_seeded_classes_expansion() -> None:
    """Promoted classes expand to their seeded instruments."""
    graph = _graph()

    assert "cattle" in graph.expand("LIVESTOCK")
    assert "rins" in graph.expand("ENVIRONMENTAL")
    assert "timber" in graph.expand("FORESTRY")
    assert "cement" in graph.expand("CONSTRUCTION")
    assert graph.unseeded_classes == ("SEAFOOD",)


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


def test_two_firms_producing_gold_unify() -> None:
    """Spot proof: FCX and NEM share the gold instrument as producers."""
    derived = _derive_all(_graph())

    producers = {
        link.firm
        for link in derived
        if link.instrument == "gold" and link.relation == "PRODUCES"
    }
    assert producers == {"FCX", "NEM"}
    consumers = {
        link.firm
        for link in derived
        if link.instrument == "natural_gas" and link.relation == "CONSUMES"
    }
    assert consumers == {"CF"}


def test_link_pattern_textblock_reads_the_coordinate() -> None:
    """Typed atoms: the coordinate decides; declaration-less keeps the token test."""
    from edgar_sec.engine.xbrl.schema.atoms import Atom
    from edgar_sec.engine.xbrl.schema.commodities import LinkPattern

    narrative = LinkPattern(
        instrument="X",
        relation="NARRATIVE",
        tokens_all=("unions",),
        textblock="require",
    )
    typed = Atom("H_UNKNOWN", frozenset({"M_TEXT_NODE"}))
    plain = Atom("H_UNKNOWN")
    narrative_tokens = ("unions", "represented")
    assert narrative.matches(typed, narrative_tokens) is True
    assert narrative.matches(plain, narrative_tokens) is False
    assert narrative.matches(plain, ("unions", "text", "block")) is True

    excluding = LinkPattern(instrument="X", relation="MEASURES")
    assert excluding.matches(typed, narrative_tokens) is False
    assert excluding.matches(plain, narrative_tokens) is True
    assert excluding.matches(plain, ("text", "block")) is False
