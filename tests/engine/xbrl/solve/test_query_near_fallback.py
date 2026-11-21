"""Tests for NEAR-fallback resolution and the text coordinate."""

from edgar_sec.domain.identity import AccessionNumber
from edgar_sec.engine.xbrl.schema.models import XbrlFact
from edgar_sec.engine.xbrl.solve.query import FinancialQuery, QueryStatus
from edgar_sec.engine.xbrl.solve.scoping import FactScope
from .query_fixtures import (
    _DURATION_SCOPE,
    _INSTANT_SCOPE,
    _duration_fact,
    _duration_usd_fact,
    _instant_fact,
    _query_engine,
    _table_declarations,
    _text_fact,
)


def test_near_fallback_resolves_subsumption_equivalent() -> None:
    """No exact revenue concept: the subsumption NEAR resolves, tiered."""
    facts = (
        _duration_fact(
            "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax", 100.0
        ),
    )
    result = _query_engine().execute(FinancialQuery("Revenues", _DURATION_SCOPE), facts)
    assert result.status == QueryStatus.REPORTED
    assert result.candidate_qnames == (
        "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
    )
    assert result.value == 100.0
    assert result.tier == "near"
    assert len(result.equivalents) == 1
    assert result.equivalents[0].rule == "subsumption"
    assert result.equivalents[0].direction == "specialization"
    assert result.equivalents[0].via_default is False


def test_near_fallback_tie_is_ambiguous_with_equivalents() -> None:
    """Two equidistant NEAR candidates tie: AMBIGUOUS, both carried."""
    facts = (
        _duration_fact("us-gaap:SalesRevenueGoodsNet", 100.0),
        _duration_fact("us-gaap:SalesRevenueNet", 200.0),
    )
    result = _query_engine().execute(FinancialQuery("Revenues", _DURATION_SCOPE), facts)
    assert result.status == QueryStatus.AMBIGUOUS
    assert result.candidate_qnames == (
        "us-gaap:SalesRevenueGoodsNet",
        "us-gaap:SalesRevenueNet",
    )
    assert {item.qname for item in result.equivalents} == set(result.candidate_qnames)
    assert result.tier == "near"
    assert all(item.rule == "subsumption" for item in result.equivalents)


def test_near_fallback_divergent_tier_never_resolves_on_distance() -> None:
    """Dist-2 sales line vs dist-3 headline, divergent values: no resolution."""
    facts = (
        _duration_fact("us-gaap:SalesRevenueNet", 148_701.0),
        _duration_fact(
            "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
            245_122.0,
        ),
    )
    result = _query_engine().execute(FinancialQuery("Revenues", _DURATION_SCOPE), facts)
    assert result.status == QueryStatus.AMBIGUOUS
    assert result.value is None
    assert result.reported_fact is None
    assert result.candidate_qnames == (
        "us-gaap:SalesRevenueNet",
        "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
    )
    assert result.tier == "near"
    assert {item.qname for item in result.equivalents} == set(result.candidate_qnames)


def test_near_fallback_agreeing_tier_resolves_to_the_best_ranked() -> None:
    """Same shape with agreeing values: the best-ranked resolves."""
    facts = (
        _duration_fact("us-gaap:SalesRevenueNet", 100.0),
        _duration_fact(
            "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax", 100.0
        ),
    )
    result = _query_engine().execute(FinancialQuery("Revenues", _DURATION_SCOPE), facts)
    assert result.status == QueryStatus.REPORTED
    assert result.candidate_qnames == ("us-gaap:SalesRevenueNet",)
    assert result.value == 100.0
    assert result.tier == "near"
    assert len(result.equivalents) == 2


def test_near_fallback_supertype_sole_candidate_is_not_promoted() -> None:
    """N-1: a sole NEAR supertype never supplies the target's value."""
    facts = (_instant_fact("us-gaap:Assets", 364_980.0),)
    result = _query_engine().execute(
        FinancialQuery("Derivative Assets", _INSTANT_SCOPE), facts
    )
    assert result.status == QueryStatus.AMBIGUOUS
    assert result.value is None
    assert result.reported_fact is None
    assert result.candidate_qnames == ("us-gaap:Assets",)
    assert result.tier == "near"
    assert len(result.equivalents) == 1
    assert result.equivalents[0].rule == "single_modifier_difference"
    assert result.equivalents[0].direction == "generalization"


def test_near_fallback_supertype_best_blocks_an_agreeing_tier() -> None:
    """Agreeing tier, supertype best: no promotion, no substitution."""
    facts = (
        _instant_fact("us-gaap:Assets", 100.0),
        _instant_fact("us-gaap:DerivativeAssetsCurrent", 100.0),
    )
    result = _query_engine().execute(
        FinancialQuery("Derivative Assets", _INSTANT_SCOPE), facts
    )
    assert result.status == QueryStatus.AMBIGUOUS
    assert result.value is None
    assert result.reported_fact is None
    assert set(result.candidate_qnames) == {
        "us-gaap:Assets",
        "us-gaap:DerivativeAssetsCurrent",
    }
    directions = {item.qname: item.direction for item in result.equivalents}
    assert directions == {
        "us-gaap:Assets": "generalization",
        "us-gaap:DerivativeAssetsCurrent": "specialization",
    }


def test_near_fallback_specialization_best_still_resolves_over_supertype() -> None:
    """Agreeing tier, specialization best: it resolves as before."""
    facts = (
        _instant_fact("us-gaap:Liabilities", 100.0),
        _instant_fact("us-gaap:AccountsPayableCurrent", 100.0),
    )
    result = _query_engine().execute(
        FinancialQuery("Accounts Payable", _INSTANT_SCOPE), facts
    )
    assert result.status == QueryStatus.REPORTED
    assert result.candidate_qnames == ("us-gaap:AccountsPayableCurrent",)
    assert result.value == 100.0
    assert result.tier == "near"
    directions = {item.qname: item.direction for item in result.equivalents}
    assert directions == {
        "us-gaap:AccountsPayableCurrent": "specialization",
        "us-gaap:Liabilities": "generalization",
    }


def test_near_fallback_candidate_without_a_single_value_blocks_resolution() -> None:
    """A tier candidate with two in-scope contexts has no single value."""
    accession = AccessionNumber("0000950170-24-087843")
    facts = (
        _duration_fact("us-gaap:SalesRevenueGoodsNet", 100.0),
        _duration_fact("us-gaap:SalesRevenueNet", 100.0),
        XbrlFact(
            accession,
            "us-gaap:SalesRevenueNet",
            100.0,
            unit="USD",
            period_type="duration",
            start_date="2022-07-01",
            end_date="2023-06-30",
        ),
    )
    scope = FactScope(accession="0000950170-24-087843", unit="USD")
    result = _query_engine().execute(FinancialQuery("Revenues", scope), facts)
    assert result.status == QueryStatus.AMBIGUOUS
    assert result.value is None
    assert set(result.candidate_qnames) == {
        "us-gaap:SalesRevenueGoodsNet",
        "us-gaap:SalesRevenueNet",
    }


def test_residual_bearing_term_gets_no_fallback() -> None:
    """A term with residuals stays UNAVAILABLE; the fallback never fires."""
    facts = (
        _duration_fact(
            "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax", 100.0
        ),
    )
    result = _query_engine().execute(
        FinancialQuery("ZebraRevenue", _DURATION_SCOPE), facts
    )
    assert result.status == QueryStatus.UNAVAILABLE
    assert result.candidate_qnames == ()
    assert result.tier == ""
    assert result.equivalents == ()


def test_unrelated_only_candidate_gives_no_result_and_no_fallback() -> None:
    """Negative pair: Revenues vs CostOfRevenue is UNRELATED end to end."""
    facts = (_duration_fact("us-gaap:CostOfRevenue", 50.0),)
    result = _query_engine().execute(FinancialQuery("Revenues", _DURATION_SCOPE), facts)
    assert result.status == QueryStatus.UNAVAILABLE
    assert result.value is None
    assert result.reported_fact is None
    assert result.candidate_qnames == ()
    assert result.tier == ""
    assert result.equivalents == ()


def test_exact_resolution_carries_equivalents() -> None:
    """Q-B: an exact resolution surfaces its ranked neighbourhood, tiered exact."""
    facts = (_duration_fact("us-gaap:NetIncomeLoss", 42.0),)
    result = _query_engine().execute(
        FinancialQuery("NetIncomeLoss", _DURATION_SCOPE), facts
    )
    assert result.status == QueryStatus.REPORTED
    assert result.value == 42.0
    assert result.tier == "exact"
    assert len(result.equivalents) == 1
    assert result.equivalents[0].qname == "us-gaap:NetIncomeLoss"
    assert result.equivalents[0].tier == "exact"
    assert result.equivalents[0].rule == "equality"
    assert result.equivalents[0].direction == ""


def test_exact_resolution_surfaces_near_neighbourhood() -> None:
    """Q-B: the ASC-606 neighbour rides beside the exact Revenues answer."""
    facts = (
        _duration_fact("us-gaap:Revenues", 100.0),
        _duration_fact(
            "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax", 100.0
        ),
    )
    result = _query_engine().execute(FinancialQuery("Revenue", _DURATION_SCOPE), facts)
    assert result.status == QueryStatus.REPORTED
    assert result.candidate_qnames == ("us-gaap:Revenues",)
    assert result.value == 100.0
    assert result.tier == "exact"
    by_qname = {item.qname: item for item in result.equivalents}
    assert by_qname["us-gaap:Revenues"].tier == "exact"
    neighbour = by_qname["us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"]
    assert neighbour.tier == "near"
    assert neighbour.rule == "subsumption"
    assert neighbour.direction == "specialization"


def test_text_only_atom_matches_leave_a_numeric_term_unavailable() -> None:
    """Only textblocks sit on the bare atom: the coordinate excludes them."""
    qnames = (
        "us-gaap:DisaggregationOfRevenueTableTextBlock",
        "us-gaap:RevenueRecognitionPolicyTextBlock",
    )
    facts = (
        _text_fact(qnames[0], "<div>rev</div>"),
        _text_fact(qnames[1], "<div>pol</div>"),
    )
    engine = _query_engine(_table_declarations(*qnames))
    result = engine.execute(FinancialQuery("Revenue", _DURATION_SCOPE), facts)
    assert result.status == QueryStatus.UNAVAILABLE
    assert result.candidate_qnames == ()
    assert result.value is None


def test_text_coordinate_excludes_a_textblock_with_numeric_facts() -> None:
    """Declared text type excludes even when numeric facts exist (not substance)."""
    qname = "us-gaap:DisaggregationOfRevenueTableTextBlock"
    facts = (_duration_fact(qname, 5.0),)
    declared = _query_engine(_table_declarations(qname))
    result = declared.execute(FinancialQuery("Revenue", _DURATION_SCOPE), facts)
    assert result.status == QueryStatus.UNAVAILABLE
    assert result.candidate_qnames == ()
    undeclared = _query_engine().execute(
        FinancialQuery("Revenue", _DURATION_SCOPE), facts
    )
    assert undeclared.status == QueryStatus.REPORTED
    assert undeclared.candidate_qnames == (qname,)


def test_text_only_candidate_does_not_crowd_a_numeric_match() -> None:
    """A textblock sharing the atom drops out; the numeric match reports."""
    facts = (
        _duration_fact("us-gaap:Revenues", 100.0),
        _text_fact("us-gaap:DisaggregationOfRevenueTableTextBlock", "<div>rev</div>"),
    )
    declarations = _table_declarations("us-gaap:DisaggregationOfRevenueTableTextBlock")
    result = _query_engine(declarations).execute(
        FinancialQuery("Revenue", _DURATION_SCOPE), facts
    )
    assert result.status == QueryStatus.REPORTED
    assert result.candidate_qnames == ("us-gaap:Revenues",)
    assert result.value == 100.0
    assert result.tier == "exact"
    assert [item.qname for item in result.equivalents] == ["us-gaap:Revenues"]


def test_literal_textblock_qname_route_is_not_guarded() -> None:
    """An explicitly named textblock stays resolvable as a candidate."""
    facts = (_text_fact("us-gaap:RevenueRecognitionPolicyTextBlock", "<div>pol</div>"),)
    result = _query_engine().execute(
        FinancialQuery("us-gaap:RevenueRecognitionPolicyTextBlock", _DURATION_SCOPE),
        facts,
    )
    assert result.status == QueryStatus.UNAVAILABLE
    assert result.candidate_qnames == ("us-gaap:RevenueRecognitionPolicyTextBlock",)
