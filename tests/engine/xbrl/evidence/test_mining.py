"""Unit tests for empirical XBRL phrase collocation mining and support counting."""

from edgar_sec.engine.xbrl.evidence.mining import (
    ArcPolarityResolver,
    CollocationMiner,
    SupportCounter,
)
from edgar_sec.engine.xbrl.schema.models import CalculationArc


def test_support_counter_scope_classification() -> None:
    """Verify support counter classifies universal, sector, and firm scopes."""
    counter = SupportCounter()
    key_univ = ("Research", "Development")
    key_sector = ("Net", "Interest")
    key_firm = ("Windows", "Commercial")

    # Universal: 2+ firms, 2+ SICs
    counter.observe(key_univ, "MSFT", "7372")
    counter.observe(key_univ, "AAPL", "3571")
    assert counter.firm_count(key_univ) == 2
    assert counter.sic_count(key_univ) == 2
    assert counter.classify_scope(key_univ) == "UNIVERSAL"

    # Sector: 2+ firms, 1 SIC
    counter.observe(key_sector, "JPM", "6021")
    counter.observe(key_sector, "BAC", "6021")
    assert counter.firm_count(key_sector) == 2
    assert counter.sic_count(key_sector) == 1
    assert counter.classify_scope(key_sector) == "SECTOR"

    # Firm: 1 firm
    counter.observe(key_firm, "MSFT", "7372")
    assert counter.firm_count(key_firm) == 1
    assert counter.classify_scope(key_firm) == "FIRM"


def test_collocation_miner_pmi() -> None:
    """Verify PMI computation and candidate phrase extraction from token sequences."""
    sequences = [
        ("Research", "And", "Development", "Expense"),
        ("Research", "And", "Development", "Costs"),
        ("Selling", "General", "And", "Administrative"),
    ]
    miner = CollocationMiner(min_pmi=0.1, min_freq=2)
    candidates = miner.mine_bigrams(sequences)

    pairs = {c.phrase for c in candidates}
    assert ("Research", "And") in pairs
    assert ("And", "Development") in pairs


def test_arc_polarity_resolver() -> None:
    """Verify calculation arcs mapped to PART_OF and CONTRA_OF candidate relations."""
    arcs = [
        CalculationArc("us-gaap:GrossProfit", "us-gaap:Revenues", 1.0),
        CalculationArc("us-gaap:GrossProfit", "us-gaap:CostOfGoodsSold", -1.0),
    ]
    relations = ArcPolarityResolver.resolve_arcs(arcs)
    assert len(relations) == 2

    rev_rel = next(r for r in relations if r.source_concept == "us-gaap:Revenues")
    assert rev_rel.relation_type == "PART_OF"
    assert rev_rel.algebraic_weight == 1.0
    assert rev_rel.formula_id == "FORMULA_GROSSPROFIT"

    cogs_rel = next(
        r for r in relations if r.source_concept == "us-gaap:CostOfGoodsSold"
    )
    assert cogs_rel.relation_type == "CONTRA_OF"
    assert cogs_rel.algebraic_weight == -1.0
