"""Equivalence dialect bridge: cross-dialect purchase and exit-act pairs."""

from __future__ import annotations

from edgar_sec.engine.xbrl.schema.atoms import Atom
from edgar_sec.engine.xbrl.solve.equivalence import (
    EXACT,
    NEAR,
    UNRELATED,
    classify_ladder_pair,
    rank_equivalents,
)
from edgar_sec.engine.xbrl.taxonomy.domain import load_domain_taxonomy
from tests.engine.xbrl.solve.equivalence_support import _atom


def test_dialect_bridge_relates_payments_and_purchase_ppe() -> None:
    """The PP&E pair classifies NEAR via the bridge in both directions."""
    tax = load_domain_taxonomy()
    payments = _atom("us-gaap:PaymentsToAcquirePropertyPlantAndEquipment")
    purchase = _atom(
        "ifrs-full:PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities"
    )
    for target, candidate in ((payments, purchase), (purchase, payments)):
        result = classify_ladder_pair(
            target,
            candidate,
            tax.default_coordinates,
            tuple(tax.sibling_groups),
            relations=tax.atom_relations,
        )
        assert result.tier == NEAR
        assert result.rule == "dialect_bridge"
        assert result.via_bridge is True
        assert result.modifier_distance == 0


def test_dialect_bridge_reaches_instrument_coordinate() -> None:
    """The HSBC instrument line bridges from the payments investment atom."""
    tax = load_domain_taxonomy()
    payments = _atom("us-gaap:PaymentsToAcquireOtherInvestments")
    purchase = _atom(
        "ifrs-full:PurchaseOfFinancialInstrumentsClassifiedAsInvestingActivities"
    )
    for target, candidate in ((payments, purchase), (purchase, payments)):
        result = classify_ladder_pair(
            target,
            candidate,
            tax.default_coordinates,
            tuple(tax.sibling_groups),
            relations=tax.atom_relations,
        )
        assert result.tier == NEAR
        assert result.rule == "dialect_bridge"
        assert result.via_bridge is True


def test_dialect_bridge_constructed_extension_pair() -> None:
    """A constructed extension purchase line bridges on its object claim."""
    tax = load_domain_taxonomy()
    payments = _atom("us-gaap:PaymentsToAcquirePropertyPlantAndEquipment")
    purchase = _atom("acme:PurchaseOfPropertyPlantAndEquipment")
    result = classify_ladder_pair(
        payments,
        purchase,
        tax.default_coordinates,
        tuple(tax.sibling_groups),
        relations=tax.atom_relations,
    )
    assert result.tier == NEAR
    assert result.rule == "dialect_bridge"


def test_dialect_bridge_sale_worded_proceeds_gain_no_bridge() -> None:
    """Sale-worded proceeds keep their stated class, unbridged.

    The sale act marker on their atoms excludes them from bridge entry.
    """
    tax = load_domain_taxonomy()
    payments = _atom("us-gaap:PaymentsToAcquirePropertyPlantAndEquipment")
    proceeds = _atom("us-gaap:ProceedsFromSaleOfPropertyPlantAndEquipment")
    purchase = _atom(
        "ifrs-full:PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities"
    )
    stated = classify_ladder_pair(
        payments,
        proceeds,
        tax.default_coordinates,
        tuple(tax.sibling_groups),
        relations=tax.atom_relations,
    )
    assert stated.tier == NEAR
    assert stated.rule == "single_modifier_difference"
    assert stated.via_bridge is False
    for target, candidate in ((purchase, proceeds), (proceeds, purchase)):
        result = classify_ladder_pair(
            target,
            candidate,
            tax.default_coordinates,
            tuple(tax.sibling_groups),
            relations=tax.atom_relations,
        )
        assert result.tier == UNRELATED
        assert result.via_bridge is False


def test_dialect_bridge_controls_stay_put() -> None:
    """Within-dialect EXACT and purchase-object mismatches are unchanged."""
    tax = load_domain_taxonomy()
    payments = _atom("us-gaap:PaymentsToAcquirePropertyPlantAndEquipment")
    productive = _atom("us-gaap:PaymentsToAcquireProductiveAssets")
    exact = classify_ladder_pair(
        payments,
        productive,
        tax.default_coordinates,
        tuple(tax.sibling_groups),
        relations=tax.atom_relations,
    )
    assert exact.tier == EXACT
    assert exact.via_bridge is False

    purchase = _atom(
        "ifrs-full:PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities"
    )
    intangibles = _atom(
        "ifrs-full:PurchaseOfIntangibleAssetsClassifiedAsInvestingActivities"
    )
    for target, candidate in (
        (purchase, intangibles),
        (intangibles, purchase),
        (payments, intangibles),
    ):
        result = classify_ladder_pair(
            target,
            candidate,
            tax.default_coordinates,
            tuple(tax.sibling_groups),
            relations=tax.atom_relations,
        )
        assert result.tier == UNRELATED
        assert result.via_bridge is False


def test_dialect_bridge_ranks_purchase_above_sale_worded_proceeds() -> None:
    """For the capex target the purchase line outranks the proceeds line."""
    tax = load_domain_taxonomy()
    assert tax.token_lexicon is not None
    target = _atom("us-gaap:PaymentsToAcquirePropertyPlantAndEquipment")
    names = (
        "us-gaap:ProceedsFromSaleOfPropertyPlantAndEquipment",
        "ifrs-full:PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities",
        "us-gaap:PaymentsToAcquireProductiveAssets",
    )
    ranked = rank_equivalents(
        "us-gaap:PaymentsToAcquirePropertyPlantAndEquipment",
        target,
        tuple((name, _atom(name)) for name in names),
        tax.default_coordinates,
        tuple(tax.sibling_groups),
        relations=tax.atom_relations,
    )
    order = [item.qname for item in ranked]
    assert order.index(names[1]) < order.index(names[0])
    bridge = next(item for item in ranked if item.qname == names[1])
    assert bridge.tier == NEAR and bridge.via_bridge is True


def test_dialect_bridge_excludes_exit_worded_proceeds() -> None:
    """Exit-worded proceeds are excluded by their act markers, not bridged.

    The disposal-worded line carries M_DISPOSAL, which bridge entry refuses.
    """
    tax = load_domain_taxonomy()
    constructed = _atom("acme:ProceedsFromDisposalOfWindTurbines")
    assert constructed == Atom("H_CASH", frozenset({"M_DISPOSAL"}))
    disposal = _atom("ifrs-full:ProceedsFromDisposalOfPropertyPlantAndEquipment")
    purchase = _atom(
        "ifrs-full:PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities"
    )
    payments = _atom("us-gaap:PaymentsToAcquirePropertyPlantAndEquipment")
    for target, candidate in ((disposal, purchase), (purchase, disposal)):
        result = classify_ladder_pair(
            target,
            candidate,
            tax.default_coordinates,
            tuple(tax.sibling_groups),
            relations=tax.atom_relations,
        )
        assert result.tier == UNRELATED
        assert result.via_bridge is False
    stated = classify_ladder_pair(
        payments,
        disposal,
        tax.default_coordinates,
        tuple(tax.sibling_groups),
        relations=tax.atom_relations,
    )
    assert stated.tier == NEAR
    assert stated.rule == "single_modifier_difference"
    assert stated.via_bridge is False


def test_dialect_bridge_refuses_a_purchase_side_exit_marker() -> None:
    """A purchase-side atom carrying an exit-act marker fails bridge entry."""
    tax = load_domain_taxonomy()
    payments = Atom("H_CASH", frozenset({"M_INVESTMENT"}))
    clean = Atom("H_ASSET", frozenset({"M_FINANCIAL_INSTRUMENT", "M_PURCHASE"}))
    marked = Atom(
        "H_ASSET",
        frozenset({"M_FINANCIAL_INSTRUMENT", "M_PURCHASE", "M_DISPOSAL"}),
    )
    control = classify_ladder_pair(
        payments,
        clean,
        tax.default_coordinates,
        tuple(tax.sibling_groups),
        relations=tax.atom_relations,
    )
    assert control.tier == NEAR and control.via_bridge is True
    refused = classify_ladder_pair(
        payments,
        marked,
        tax.default_coordinates,
        tuple(tax.sibling_groups),
        relations=tax.atom_relations,
    )
    assert refused.tier == UNRELATED
    assert refused.via_bridge is False


def test_dialect_bridge_requires_the_bare_payments_coordinate() -> None:
    """Refined or compound payments-side atoms fail bridge entry.

    Entry names the dialect's bare object coordinate alone.
    """
    tax = load_domain_taxonomy()
    purchase = _atom(
        "ifrs-full:PurchaseOfFinancialInstrumentsClassifiedAsInvestingActivities"
    )
    refined = _atom("us-gaap:PaymentsToAcquireHeldToMaturitySecurities")
    compound = _atom("us-gaap:PaymentsForProceedsFromShortTermInvestments")
    for payments in (refined, compound):
        result = classify_ladder_pair(
            payments,
            purchase,
            tax.default_coordinates,
            tuple(tax.sibling_groups),
            relations=tax.atom_relations,
        )
        assert result.tier == UNRELATED
        assert result.via_bridge is False


def test_sale_and_disposal_gains_share_the_gain_identity() -> None:
    """Sale-gain and disposal-gain atoms both carry M_DISPOSAL_GAIN."""
    sale = _atom("us-gaap:GainLossOnSaleOfBusiness")
    disposal = _atom(
        "ifrs-full:AdjustmentsForGainLossOnDisposalOfInvestmentsInSubsidiariesJointVenturesAndAssociates"
    )
    assert "M_DISPOSAL_GAIN" in sale.modifiers
    assert "M_DISPOSAL_GAIN" in disposal.modifiers
    assert "M_SALE" in sale.modifiers
    assert "M_DISPOSAL" in disposal.modifiers


def test_exit_act_swap_scope() -> None:
    """Exit twins swap on gain, cash, and asset coordinates only.

    Sparse coordinates state no exit kinship and refuse the swap.
    """
    tax = load_domain_taxonomy()

    def classify(target: str, candidate: str):
        return classify_ladder_pair(
            _atom(target),
            _atom(candidate),
            tax.default_coordinates,
            tuple(tax.sibling_groups),
            relations=tax.atom_relations,
        )

    gain = classify(
        "acme:GainOnSaleOfWindTurbines", "acme:GainLossOnDisposalOfWindTurbines"
    )
    assert gain.tier == NEAR and gain.rule == "sibling_swap"
    proceeds = classify(
        "acme:ProceedsFromSaleOfWindTurbines",
        "acme:ProceedsFromDisposalOfWindTurbines",
    )
    assert proceeds.tier == NEAR and proceeds.rule == "sibling_swap"
    asset = classify(
        "ext:SaleOfSolarGenerationEquipment", "ext:DisposalsOfSolarGenerationEquipment"
    )
    assert asset.tier == NEAR and asset.rule == "sibling_swap"
    sparse = classify(
        "srt:ProvedDevelopedAndUndevelopedReservesSalesOfMineralsInPlace",
        "us-gaap:LiabilityForFuturePolicyBenefitExpectedFuturePolicyBenefitDerecognition",
    )
    assert sparse.tier == UNRELATED


def test_dialect_bridge_reaches_securities_purchase_lines() -> None:
    """The AFS and amortised-cost purchase lines bridge on their object claim."""
    tax = load_domain_taxonomy()
    payments = _atom("us-gaap:PaymentsToAcquireOtherInvestments")
    for name in (
        "ifrs-full:PurchaseOfAvailableforsaleFinancialAssets",
        "ifrs-full:PurchaseOfFinancialAssetsMeasuredAtAmortisedCostClassifiedAsInvestingActivities",
        "ifrs-full:PurchaseOfFinancialAssetsMeasuredAtFairValueThroughProfitOrLossClassifiedAsInvestingActivities",
    ):
        result = classify_ladder_pair(
            payments,
            _atom(name),
            tax.default_coordinates,
            tuple(tax.sibling_groups),
            relations=tax.atom_relations,
        )
        assert result.tier == NEAR
        assert result.rule == "dialect_bridge"
        assert result.via_bridge is True
