"""Tests for arc-based atom relation mining with evidence tiers."""

from __future__ import annotations

import pyarrow as pa

from edgar_sec.engine.xbrl.discovery.fixture_miner import BundleFacts
from edgar_sec.engine.xbrl.discovery.relation_miner import mine_atom_relations
from edgar_sec.engine.xbrl.normalize.lexicon import TokenLexicon
from edgar_sec.engine.xbrl.paths import resolve_xbrl_paths


def _bundle(firm: str, sic: str, calc: list, pre: list) -> BundleFacts:
    """Build a bundle carrying only arc tables for relation mining."""
    facts = pa.table({"concept_qname": ["us-gaap:Revenues"]})
    calc_table = pa.table(
        {
            "parent_qname": [p for p, _c, _w in calc],
            "child_qname": [c for _p, c, _w in calc],
            "weight": [w for _p, _c, w in calc],
        }
    )
    pre_table = pa.table(
        {
            "parent_qname": [p for p, _c in pre],
            "child_qname": [c for _p, c in pre],
        }
    )
    return BundleFacts(
        firm=firm,
        sic_code=sic,
        facts=facts,
        calculation_arcs=calc_table,
        presentation_arcs=pre_table,
    )


def test_mines_calc_part_of_and_presentation_placement() -> None:
    """Calc arcs yield PART_OF at calculation tier; pre arcs yield PLACEMENT."""
    lexicon = TokenLexicon.load_json(resolve_xbrl_paths().default_token_lexicon_path)
    calc = [("us-gaap:GrossProfit", "us-gaap:Revenues", 1.0)]
    pre = [("us-gaap:Assets", "us-gaap:CashAndCashEquivalentsAtCarryingValue")]
    bundles = [_bundle(f"F{i}", str(1000 + i), calc, pre) for i in range(5)]

    mined = mine_atom_relations(bundles, lexicon)

    by_type = {r.relation_type: r for r in mined}
    part = by_type["PART_OF"]
    assert part.evidence == "calculation"
    assert part.source.head == "H_REVENUE"
    assert part.target.head == "H_INCOME"
    assert part.weight == 1.0
    assert part.firm_count == 5
    placement = by_type["PLACEMENT"]
    assert placement.evidence == "presentation"
    assert placement.source.head == "H_CASH"
    assert placement.target.head == "H_ASSET"


def test_thresholds_and_unknown_heads_are_filtered() -> None:
    """Below-threshold pairs and unknown-head endpoints never surface."""
    lexicon = TokenLexicon.load_json(resolve_xbrl_paths().default_token_lexicon_path)
    calc = [("us-gaap:GrossProfit", "us-gaap:Revenues", 1.0)]
    bundles = [_bundle("F0", "1000", calc, []), _bundle("F1", "1001", calc, [])]

    assert mine_atom_relations(bundles, lexicon) == ()
