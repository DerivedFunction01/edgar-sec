"""Equivalence ranking: renamed and extension concepts share atom coordinates."""

from __future__ import annotations

from edgar_sec.engine.xbrl.normalize.decomposer import decompose_concept
from edgar_sec.engine.xbrl.schema.atoms import Atom
from edgar_sec.engine.xbrl.solve.equivalence import (
    EXACT,
    NEAR,
    UNRELATED,
    classify_ladder_pair,
    classify_pair,
    rank_equivalents,
)
from edgar_sec.engine.xbrl.taxonomy.domain import load_domain_taxonomy
from tests.engine.xbrl.solve.equivalence_support import _atom


def test_renamed_revenue_concepts_are_near_equivalents() -> None:
    """Post-ASC-606 revenue decomposes compositionally: subsumption NEAR.

    Re-adjudicated in Phase 0: the former EXACT was a whole-phrase artifact.
    """
    pre_asc606 = _atom("us-gaap:Revenues")
    post_asc606 = _atom("us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax")
    assert classify_pair(pre_asc606, post_asc606) == NEAR


def test_extension_reconciliation_item_matches_us_gaap_atom() -> None:
    """A firm extension lands one modifier from its us-gaap sibling.

    The sibling states its disposal subject; the extension states no act.
    """
    extension = _atom(
        "aapl:EffectiveIncomeTaxRateReconciliationImpactOfTheStateAidDecisionAmount"
    )
    standard = _atom(
        "us-gaap:EffectiveIncomeTaxRateReconciliationDispositionOfBusiness"
    )
    assert classify_pair(extension, standard) == NEAR


def test_property_plant_and_equipment_head_is_modelled() -> None:
    """PPE net decomposes to the tangible-asset coordinate, not UNKNOWN."""
    atom = _atom("us-gaap:PropertyPlantAndEquipmentNet")
    assert atom.head == "H_ASSET"
    assert "M_PPE_TANGIBLE" in atom.modifiers


def test_lattice_neighbours_are_near_not_exact() -> None:
    """Subsumption and one-modifier differences classify as near."""
    bare = Atom("H_ASSET")
    qualified = Atom("H_ASSET", frozenset({"M_RECEIVABLE"}))
    other_head = Atom("H_LIABILITY", frozenset({"M_RECEIVABLE"}))
    far = Atom("H_ASSET", frozenset({"M_CURRENT", "M_FAIR_VALUE"}))
    assert classify_pair(bare, qualified) == NEAR
    assert classify_pair(bare, other_head) == UNRELATED
    assert classify_pair(qualified, far) == UNRELATED


def test_maturity_buckets_are_exact_despite_different_number_indexicals() -> None:
    """Same atom, different num indexical: exact equivalence, bucket apart."""
    tax = load_domain_taxonomy()
    assert tax.token_lexicon is not None
    five_atom, _, _, five_idx = decompose_concept(
        "amzn:FinancingObligationsFutureMinimumPaymentsDueInFiveYears",
        tax.token_lexicon,
    )
    three_atom, _, _, three_idx = decompose_concept(
        "amzn:FinancingObligationsFutureMinimumPaymentsDueInThreeYears",
        tax.token_lexicon,
    )
    assert classify_pair(five_atom, three_atom) == EXACT
    assert five_idx == ("num=5",)
    assert three_idx == ("num=3",)


def test_same_number_does_not_merge_modifier_variants() -> None:
    """Equal num indexicals do not override a modifier difference (NEAR)."""
    afs = _atom(
        "us-gaap:DebtSecuritiesAvailableForSaleMaturityAfter10YearsWeightedAverageYield"
    )
    htm = _atom(
        "us-gaap:DebtSecuritiesHeldToMaturityMaturityAfter10YearsWeightedAverageYield"
    )
    assert classify_pair(afs, htm) == NEAR


def test_rank_equivalents_orders_exact_before_near() -> None:
    """Ranking puts exact matches first and drops unrelated candidates."""
    target = Atom("H_REVENUE", frozenset({"M_SALES_GOODS"}))
    candidates = (
        ("firm-b:Revenues", Atom("H_REVENUE")),
        ("firm-a:SalesRevenueNet", Atom("H_REVENUE", frozenset({"M_SALES_GOODS"}))),
        ("firm-c:CostOfRevenue", Atom("H_COST")),
    )
    ranked = rank_equivalents("firm-x:SalesRevenueNet", target, candidates)
    assert [item.qname for item in ranked] == [
        "firm-a:SalesRevenueNet",
        "firm-b:Revenues",
    ]
    assert [item.tier for item in ranked] == [EXACT, NEAR]


def test_bare_head_equality_is_near_not_exact() -> None:
    """F-WS4S3-1: distinct concepts sharing only a bare head are not identical."""
    bare = Atom("H_ASSET")
    assert classify_pair(bare, Atom("H_ASSET")) == NEAR
    assert classify_pair(bare, Atom("H_ASSET"), same_qname=True) == EXACT
    ladder = classify_ladder_pair(bare, Atom("H_ASSET"))
    assert ladder.tier == NEAR and ladder.rule == "bare_head_equality"
    assert ladder.modifier_distance == 0
    ranked = rank_equivalents(
        "firm-x:Assets", bare, (("firm-a:OtherReceivables", Atom("H_ASSET")),)
    )
    assert ranked[0].tier == NEAR and ranked[0].rule == "bare_head_equality"
    atom_ranked = rank_equivalents(
        "", bare, (("firm-a:OtherReceivables", Atom("H_ASSET")),)
    )
    assert atom_ranked[0].tier == EXACT and atom_ranked[0].rule == "equality"


def test_related_party_financing_distinction_is_near_across_firms() -> None:
    """Ford's finance-receivable carriage distinguishes its related-party line."""
    ford = _atom("f:RelatedPartyTransactionFinanceReceivablesNet")
    coke = _atom("ko:RelatedPartyTransactionNetReceivablesDueFromRelatedParty")
    assert "M_RELATED_PARTY" in ford.modifiers
    assert "M_FINANCING_RECEIVABLE" in ford.modifiers
    assert "M_FINANCING_RECEIVABLE" not in coke.modifiers
    assert classify_pair(ford, coke) == NEAR


def test_ordinal_obligation_siblings_are_exact() -> None:
    """Ordinal slots differ as indexicals, so the pair classifies EXACT."""
    second = _atom("us-gaap:ContractualObligationDueInSecondYear")
    fifth = _atom("us-gaap:ContractualObligationDueInFifthYear")
    assert classify_pair(second, fifth) == EXACT


def test_sibling_classification_swap_is_near_not_exact() -> None:
    """AFS and HTM classifications are distinct modifiers in sibling swap."""
    afs = _atom(
        "us-gaap:DebtSecuritiesAvailableForSaleMaturityAfter10YearsWeightedAverageYield"
    )
    htm = _atom(
        "us-gaap:DebtSecuritiesHeldToMaturityMaturityAfter10YearsWeightedAverageYield"
    )
    assert "M_AVAILABLE_FOR_SALE" in afs.modifiers
    assert "M_HELD_TO_MATURITY" in htm.modifiers
    assert "M_PURPOSE_SALE" not in afs.modifiers
    assert classify_pair(afs, htm) == NEAR


def test_sibling_swap_with_extra_difference_is_unrelated() -> None:
    """A sibling swap plus any other modifier difference breaks nearness."""
    afs = Atom("H_ASSET", frozenset({"M_AVAILABLE_FOR_SALE", "M_DEBT"}))
    htm = Atom("H_ASSET", frozenset({"M_HELD_TO_MATURITY", "M_DEBT", "M_FAIR_VALUE"}))
    assert classify_pair(afs, htm) == UNRELATED


def test_ranked_equivalents_name_the_deciding_rule() -> None:
    """Rule provenance: equality, subsumption, and widening name themselves."""
    target = Atom("H_REVENUE")
    ranked = rank_equivalents(
        "firm-x:Revenues",
        target,
        (
            ("firm-a:Revenues", Atom("H_REVENUE")),
            (
                "firm-b:RevenueFromContractWithCustomerExcludingAssessedTax",
                _atom("us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"),
            ),
        ),
    )
    rules = {item.qname: item.rule for item in ranked}
    assert rules == {
        "firm-a:Revenues": "bare_head_equality",
        "firm-b:RevenueFromContractWithCustomerExcludingAssessedTax": "subsumption",
    }

    base = Atom("H_ASSET", frozenset({"M_FAIR_VALUE"}))
    wide = rank_equivalents(
        "firm-x:Base",
        base,
        (("firm-a:Wide", Atom("H_ASSET", frozenset({"M_FAIR_VALUE", "M_AGGREGATE"}))),),
    )
    assert wide[0].tier == NEAR and wide[0].rule == "aggregate_widening"


def test_ranked_equivalents_name_the_subsumption_direction() -> None:
    """Direction provenance: generalization, specialization, or neither."""
    target = Atom("H_ASSET", frozenset({"M_DERIVATIVE"}))
    ranked = rank_equivalents(
        "firm-x:DerivativeAssets", target, (("firm-a:Assets", Atom("H_ASSET")),)
    )
    assert ranked[0].rule == "single_modifier_difference"
    assert ranked[0].direction == "generalization"

    bare = Atom("H_REVENUE")
    asc606 = _atom("us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax")
    ranked = rank_equivalents("firm-x:Revenues", bare, (("firm-a:Asc606", asc606),))
    assert ranked[0].rule == "subsumption"
    assert ranked[0].direction == "specialization"

    ranked = rank_equivalents("firm-x:Asc606", asc606, (("firm-a:Revenues", bare),))
    assert ranked[0].rule == "subsumption"
    assert ranked[0].direction == "generalization"

    afs = Atom("H_ASSET", frozenset({"M_AVAILABLE_FOR_SALE"}))
    htm = Atom("H_ASSET", frozenset({"M_HELD_TO_MATURITY"}))
    ranked = rank_equivalents("firm-x:Afs", afs, (("firm-a:Htm", htm),))
    assert ranked[0].rule == "sibling_swap"
    assert ranked[0].direction == ""

    ranked = rank_equivalents(
        "firm-x:Revenues", bare, (("firm-a:Revenues", Atom("H_REVENUE")),)
    )
    assert ranked[0].tier == NEAR and ranked[0].direction == ""


def test_rank_equivalents_breaks_ties_on_residual_counts() -> None:
    """Equal ranks order by intent count, then total count, then qname."""
    target = Atom("H_REVENUE")
    atom = Atom("H_REVENUE", frozenset({"M_SALES_GOODS"}))
    candidates = (
        ("firm-a:Noisy", atom),
        ("firm-b:Intentful", atom),
        ("firm-c:Clean", atom),
    )
    counts = {
        "firm-a:Noisy": (0, 3),
        "firm-b:Intentful": (1, 1),
        "firm-c:Clean": (0, 0),
    }
    ranked = rank_equivalents(
        "firm-x:Revenues", target, candidates, residual_counts=counts
    )
    assert [item.qname for item in ranked] == [
        "firm-c:Clean",
        "firm-a:Noisy",
        "firm-b:Intentful",
    ]
    assert (ranked[0].residual_intent_count, ranked[0].residual_total_count) == (0, 0)
    assert (ranked[1].residual_intent_count, ranked[1].residual_total_count) == (0, 3)
    assert (ranked[2].residual_intent_count, ranked[2].residual_total_count) == (1, 1)


def test_bac_xva_dissolves_to_near_against_plain_derivative_assets() -> None:
    """The valuation-adjustment coordinate ends the XVA false EXACT.
    Re-adjudicated pin: the residual-ordered EXACT pool no longer exists.
    """
    target = _atom("us-gaap:DerivativeAssets")
    xva = "bac:DerivativeFundingRiskValuationAdjustmentDerivativeAssets"
    cva = "us-gaap:DerivativeCreditRiskValuationAdjustmentDerivativeAssets"
    assert classify_pair(target, _atom(xva)) == NEAR
    assert classify_pair(_atom(xva), _atom(cva)) == NEAR
    candidates = (
        (xva, _atom(xva)),
        (cva, _atom(cva)),
        ("us-gaap:DerivativeAssets", target),
    )
    ranked = rank_equivalents("firm-x:DerivativeAssets", target, candidates)
    assert [item.qname for item in ranked] == ["us-gaap:DerivativeAssets", xva, cva]
    assert [item.tier for item in ranked] == [EXACT, NEAR, NEAR]
    assert [item.rule for item in ranked] == [
        "equality",
        "single_modifier_difference",
        "subsumption",
    ]
    assert [item.direction for item in ranked] == [
        "",
        "specialization",
        "specialization",
    ]


def test_rank_equivalents_orders_jpm_revenue_pool_on_total_count() -> None:
    """Intent ties at zero; the digit residual's total count discriminates."""
    target = Atom("H_REVENUE")
    candidates = (
        ("jpm:FeesAndCommissions1", Atom("H_REVENUE")),
        ("us-gaap:Revenues", Atom("H_REVENUE")),
    )
    counts = {"us-gaap:Revenues": (0, 0), "jpm:FeesAndCommissions1": (0, 1)}
    ranked = rank_equivalents(
        "firm-x:Revenue", target, candidates, residual_counts=counts
    )
    assert [item.qname for item in ranked] == [
        "us-gaap:Revenues",
        "jpm:FeesAndCommissions1",
    ]


def test_sibling_swap_rule_is_named() -> None:
    """The AFS/HTM pair ranks NEAR under the sibling_swap rule."""
    afs = _atom(
        "us-gaap:DebtSecuritiesAvailableForSaleMaturityAfter10YearsWeightedAverageYield"
    )
    htm = _atom(
        "us-gaap:DebtSecuritiesHeldToMaturityMaturityAfter10YearsWeightedAverageYield"
    )
    ranked = rank_equivalents("firm-x:Afs", afs, (("firm-a:Htm", htm),))
    assert ranked[0].tier == NEAR and ranked[0].rule == "sibling_swap"
