"""Tests for the domain.world geography substrate."""

from __future__ import annotations

import json
from pathlib import Path

from edgar_sec.domain.world.geography import (
    ancestors,
    decomposition_schemes,
    domicile_node,
    is_contained,
    node_for_token,
    nodes,
    place_terms,
    resolve,
)
from edgar_sec.domain.world.geography_edges import EDGES
from edgar_sec.domain.world.geography_places import COUNTRIES, REGIONS

_TAXONOMY_DIR = (
    Path(__file__).resolve().parents[3] / "edgar_sec" / "engine" / "xbrl" / "taxonomy"
)


def test_dag_shape_is_the_declared_standing() -> None:
    assert len(EDGES) == 94
    assert len(nodes()) == 73
    assert len(COUNTRIES) == 52
    assert len(REGIONS) == 20
    assert len(decomposition_schemes()) == 18


def test_country_records_cover_exactly_the_dag_countries() -> None:
    dag_countries = {
        edge.child.split(":", 1)[1]
        for edge in EDGES
        if edge.child.startswith("country:")
    } | {
        edge.parent.split(":", 1)[1]
        for edge in EDGES
        if edge.parent.startswith("country:")
    }
    assert dag_countries == set(COUNTRIES)
    assert COUNTRIES["MX"].name == "Mexico"
    assert "mexico" in COUNTRIES["MX"].phrases


def test_resolution_matches_production_semantics() -> None:
    resolved = resolve("country:MX")
    assert resolved is not None
    assert resolved.canonical_node == "country:MX"
    assert resolved.is_foreign
    assert not resolved.is_domestic
    assert set(resolved.decomposition_schemes) == {
        "D_GEO_CORP_LATAM",
        "D_GEO_USMCA",
        "D_GEO_AMER",
        "D_GEO_GLOBAL",
    }
    assert "srt:LatinAmericaMember" in resolved.ancestor_regions
    assert "srt:AmericasMember" in resolved.ancestor_regions
    us = resolve("country:US")
    assert us is not None and us.is_domestic
    region = resolve("srt:NorthAmericaMember")
    assert region is not None and not region.is_domestic


def test_node_lookup_and_containment() -> None:
    assert node_for_token("MX") == "country:MX"
    assert node_for_token("country:JP") == "country:JP"
    assert node_for_token("LatinAmericaMember") == "srt:LatinAmericaMember"
    assert node_for_token("not-a-place") is None
    assert is_contained("country:MX", "srt:AmericasMember")
    assert not is_contained("srt:AmericasMember", "country:MX")
    assert "srt:SegmentGeographicalDomain" in ancestors("country:MX")


def test_domicile_gap_is_honest_absence() -> None:
    assert domicile_node("US") == "country:US"
    assert domicile_node("CW") is None
    assert domicile_node("IE") is None


def test_place_vocabulary_carries_countries_and_regions() -> None:
    terms = place_terms()
    for term in ("taiwan", "china", "europe", "north america", "united states"):
        assert term in terms


def test_tree_currency_datasets_sit_inside_the_substrate() -> None:
    """Validation: every currency code the tree's datasets name stands here."""
    from edgar_sec.domain.world.currencies import CURRENCIES

    units = json.loads((_TAXONOMY_DIR / "units.json").read_text(encoding="utf-8"))
    unit_codes = {
        str(row["currency_code"]) for row in units if row.get("currency_code")
    }
    assert unit_codes <= set(CURRENCIES)

    industries = json.loads(
        (_TAXONOMY_DIR / "industries.json").read_text(encoding="utf-8")
    )
    functional = {
        str(row["functional_currency"])
        for row in industries
        if row.get("functional_currency")
    }
    # DKK stands here because an industries profile names it; before
    # the substrate, no currency standing in the tree carried it.
    assert "DKK" in functional
    assert functional <= set(CURRENCIES)
