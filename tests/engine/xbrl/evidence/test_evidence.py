"""Unit tests for scoped evidence knowledge base and cryptographic freeze."""

import pytest
from edgar_sec.engine.xbrl.taxonomy.domain import DomainTaxonomy
from edgar_sec.engine.xbrl.taxonomy.records import GeoHierarchyEdge
from edgar_sec.engine.xbrl.evidence.evidence import (
    EvidenceKnowledgeBase,
    UnificationRule,
)


def test_evidence_scope_specificity() -> None:
    """Verify 4-tier scope backoff specificity levels."""
    scope1 = ("MSFT", "Technology", "2024")
    spec1, tier1 = EvidenceKnowledgeBase.scope_specificity(
        scope1, "MSFT", "Technology", 2024
    )
    assert spec1 == 4
    assert tier1 == "TIER_1_FIRM_SECTOR_YEAR"

    scope2 = ("MSFT", "Technology", "*")
    spec2, tier2 = EvidenceKnowledgeBase.scope_specificity(
        scope2, "MSFT", "Technology", 2024
    )
    assert spec2 == 3
    assert tier2 == "TIER_2_FIRM_SECTOR"

    scope3 = ("*", "Technology", "*")
    spec3, tier3 = EvidenceKnowledgeBase.scope_specificity(
        scope3, "MSFT", "Technology", 2024
    )
    assert spec3 == 2
    assert tier3 == "TIER_3_SECTOR"

    scope4 = ("*", "*", "*")
    spec4, tier4 = EvidenceKnowledgeBase.scope_specificity(
        scope4, "MSFT", "Technology", 2024
    )
    assert spec4 == 1
    assert tier4 == "TIER_4_UNIVERSAL"


def test_evidence_laplace_confidence() -> None:
    """Verify Laplace smoothing (n + 1) / (N + 2)."""
    assert EvidenceKnowledgeBase.laplace_confidence(24, 25) == 0.9259
    assert EvidenceKnowledgeBase.laplace_confidence(0, 0) == 0.5


def test_evidence_cryptographic_freeze() -> None:
    """Verify read-only lock and SHA-256 seal after freeze."""
    tax = DomainTaxonomy(prime_heads=(), subatomic_modifiers=())
    kb = EvidenceKnowledgeBase(taxonomy=tax)
    rule = UnificationRule("R1", "us-gaap:Revenues", "us-gaap:Revenues")
    kb.add_rule(rule)

    digest = kb.freeze()
    assert kb.is_frozen
    assert kb.frozen_sha256 == digest

    with pytest.raises(RuntimeError):
        kb.add_rule(UnificationRule("R2", "us-gaap:GrossProfit", "us-gaap:GrossProfit"))


def test_evidence_geography_subsumption() -> None:
    """Verify topological subsumption in geography DAG."""
    edges = (
        GeoHierarchyEdge("country:MX", "srt:LatinAmericaMember"),
        GeoHierarchyEdge("srt:LatinAmericaMember", "srt:AmericasMember"),
    )
    tax = DomainTaxonomy(
        prime_heads=(),
        subatomic_modifiers=(),
        geography_edges=edges,
    )
    kb = EvidenceKnowledgeBase(taxonomy=tax)

    assert kb.is_geo_subsumed("country:MX", "srt:LatinAmericaMember")
    assert kb.is_geo_subsumed("country:MX", "srt:AmericasMember")
    assert not kb.is_geo_subsumed("srt:AmericasMember", "country:MX")
