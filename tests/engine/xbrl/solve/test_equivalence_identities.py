"""Equivalence identities: concept identity and sibling-concept pairs."""

from __future__ import annotations

from edgar_sec.engine.xbrl.schema.atoms import Atom
from edgar_sec.engine.xbrl.solve.equivalence import (
    EXACT,
    NEAR,
    UNRELATED,
    classify_pair,
    rank_equivalents,
)
from tests.engine.xbrl.solve.equivalence_support import _atom


def test_coin_crypto_cost_matches_us_gaap_sibling_exactly() -> None:
    """Coinbase's extension crypto cost and the us-gaap sibling share an atom."""
    coin = _atom("coin:CryptoAssetCostBorrowed")
    sibling = _atom("us-gaap:CryptoAssetCost")
    assert classify_pair(coin, sibling) == EXACT


def test_gold_producers_unify_across_firms_via_commodity_modifier() -> None:
    """FCX and NEM gold concepts are near through M_COMMODITY_GOLD."""
    fcx = _atom("fcx:SaleOfGold")
    nem = _atom("nem:GoldDorePurityMarketStandard")
    assert "M_COMMODITY_GOLD" in fcx.modifiers
    assert "M_COMMODITY_GOLD" in nem.modifiers
    assert classify_pair(fcx, nem) == NEAR


def test_accounts_payable_keeps_distinct_identity() -> None:
    """Accounts payable is its own concept: exact only against itself."""
    payable = _atom("us-gaap:AccountsPayableCurrent")
    trade = _atom("us-gaap:AccountsPayableTradeCurrent")
    accrued = _atom("us-gaap:AccruedLiabilitiesCurrent")
    total = _atom("us-gaap:LiabilitiesCurrent")
    assert "M_ACCOUNTS_PAYABLE" in payable.modifiers
    assert classify_pair(payable, trade) == EXACT
    assert classify_pair(payable, accrued) == NEAR
    assert classify_pair(payable, total) == NEAR


def test_compound_payable_and_accrued_claims_both_identities() -> None:
    """The compound current-liability line carries both identity modifiers."""
    compound = _atom("us-gaap:AccountsPayableAndAccruedLiabilitiesCurrent")
    payable = _atom("us-gaap:AccountsPayableCurrent")
    assert "M_ACCOUNTS_PAYABLE" in compound.modifiers
    assert "M_ACCRUED_LIABILITY" in compound.modifiers
    assert classify_pair(compound, payable) == NEAR


def test_net_and_gross_presentations_are_sibling_swaps() -> None:
    """Gross and net PPE are distinct presentations of one carrying amount."""
    gross = _atom("us-gaap:PropertyPlantAndEquipmentGross")
    net = _atom("us-gaap:PropertyPlantAndEquipmentNet")
    assert "V_GROSS" in gross.modifiers
    assert "V_NET" in net.modifiers
    assert classify_pair(gross, net) == NEAR


def test_basic_and_diluted_eps_are_sibling_swaps() -> None:
    """Basic and diluted EPS differ only by the EPS-basis sibling swap."""
    basic = _atom("us-gaap:EarningsPerShareBasic")
    diluted = _atom("us-gaap:EarningsPerShareDiluted")
    assert classify_pair(basic, diluted) == NEAR


def test_aggregate_scope_widening_is_near() -> None:
    """Aggregate differs from its base only by scope: NEAR, by named rule."""
    base = Atom("H_ASSET", frozenset({"M_FAIR_VALUE"}))
    wide = Atom("H_ASSET", frozenset({"M_FAIR_VALUE", "M_AGGREGATE"}))
    other = Atom("H_ASSET", frozenset({"M_FAIR_VALUE", "M_TAX"}))
    assert classify_pair(base, wide) == NEAR
    assert classify_pair(wide, other) == UNRELATED


def test_dual_valuation_atom_is_near_not_a_sibling_swap() -> None:
    """An atom carrying both V_NET and V_GROSS binds them to different nouns."""
    dual = Atom("H_ASSET", frozenset({"V_NET", "V_GROSS"}))
    bare = Atom("H_ASSET")
    net_only = Atom("H_ASSET", frozenset({"V_NET"}))
    assert classify_pair(dual, bare) == NEAR
    assert classify_pair(dual, net_only) == NEAR
    assert classify_pair(dual, bare) != EXACT


def test_current_and_noncurrent_are_horizon_siblings() -> None:
    """Current and noncurrent portions of one account are near, not exact."""
    current = Atom("H_LIABILITY", frozenset({"M_CURRENT", "M_DEBT"}))
    noncurrent = Atom("H_LIABILITY", frozenset({"M_NONCURRENT", "M_DEBT"}))
    assert classify_pair(current, noncurrent) == NEAR


def test_anticipated_terms_decompose_to_modelled_atoms() -> None:
    """Taxonomy-only terms land on modelled coordinates ahead of attestation."""
    accrued_rent = _atom("us-gaap:AccruedRentCurrent")
    fhlb = _atom("us-gaap:FederalHomeLoanBankAdvances")
    crypto = _atom("us-gaap:CryptoAssetFairValueNoncurrent")
    fed_funds = _atom("us-gaap:FederalFundsPurchased")
    assert accrued_rent.head == "H_LIABILITY"
    assert "M_ACCRUED_LIABILITY" in accrued_rent.modifiers
    assert fhlb.head == "H_LIABILITY" and "M_DEBT" in fhlb.modifiers
    assert crypto.head == "H_ASSET" and "M_CRYPTO_DIGITAL" in crypto.modifiers
    assert fed_funds.head == "H_LIABILITY" and "M_DEBT" in fed_funds.modifiers


def test_common_and_preferred_shares_are_sibling_classes() -> None:
    """Common and preferred share counts are distinct concepts, near kin."""
    common = _atom("us-gaap:CommonStockSharesOutstanding")
    preferred = _atom("us-gaap:PreferredStockSharesOutstanding")
    assert "M_COMMON" in common.modifiers
    assert "M_PREFERRED" in preferred.modifiers
    assert classify_pair(common, preferred) == NEAR
    assert classify_pair(common, common) == EXACT


def test_deferred_income_tax_expense_separates_from_the_total() -> None:
    """The deferred portion is a specialization of total income tax expense."""
    deferred = _atom("us-gaap:DeferredIncomeTaxExpenseBenefit")
    total = _atom("us-gaap:IncomeTaxExpenseBenefit")
    current = _atom("us-gaap:CurrentIncomeTaxExpenseBenefit")
    assert deferred.modifiers == frozenset({"M_DEFERRED", "M_TAX"})
    assert total.modifiers == frozenset({"M_TAX"})
    assert current.modifiers == frozenset({"M_CURRENT", "M_TAX"})
    ranked = rank_equivalents(
        "us-gaap:IncomeTaxExpenseBenefit", total, (("us-gaap:X", deferred),)
    )
    assert ranked[0].tier == NEAR and ranked[0].rule == "single_modifier_difference"
    assert ranked[0].modifier_distance == 1
    assert ranked[0].direction == "specialization"


def test_deferred_income_tax_liabilities_leave_the_payable_atom() -> None:
    """Deferred tax liabilities no longer share the accrued-tax coordinate."""
    deferred = _atom("us-gaap:DeferredIncomeTaxLiabilities")
    accrued = _atom("us-gaap:AccruedIncomeTaxes")
    assert deferred.modifiers == frozenset({"M_DEFERRED", "M_TAX"})
    assert accrued.modifiers == frozenset({"M_TAX"})
    assert classify_pair(deferred, accrued) == NEAR


def test_deferred_rollforward_twin_separates_from_recognized_twin() -> None:
    """The MSFT deferred rollforward and its recognized twin are not exact."""
    deferred = _atom("msft:ContractWithCustomerLiabilityRevenueDeferred")
    recognized = _atom("us-gaap:ContractWithCustomerLiabilityRevenueRecognized")
    assert "M_DEFERRED" in deferred.modifiers
    assert "M_DEFERRED" not in recognized.modifiers
    assert classify_pair(deferred, recognized) == NEAR


def test_deferred_rollforward_leaves_the_revenue_ranking() -> None:
    """F5: the liability-family rollforward is absent from Revenues ranking."""
    target = _atom("us-gaap:Revenues")
    candidates = (
        (
            "msft:ContractWithCustomerLiabilityRevenueDeferred",
            _atom("msft:ContractWithCustomerLiabilityRevenueDeferred"),
        ),
        (
            "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
            _atom("us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"),
        ),
    )
    ranked = rank_equivalents("us-gaap:Revenues", target, candidates)
    by_qname = {item.qname: item for item in ranked}
    assert "msft:ContractWithCustomerLiabilityRevenueDeferred" not in by_qname
    headline = by_qname["us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"]
    assert headline.modifier_distance == 3


def test_deferred_is_not_a_maturity_sibling() -> None:
    """A Deferred/Noncurrent-only difference never classifies by sibling swap."""
    deferred = Atom("H_LIABILITY", frozenset({"M_DEFERRED"}))
    noncurrent = Atom("H_LIABILITY", frozenset({"M_NONCURRENT"}))
    assert classify_pair(deferred, noncurrent) == UNRELATED
    deferred_tax = Atom("H_EXPENSE", frozenset({"M_DEFERRED", "M_TAX"}))
    noncurrent_tax = Atom("H_EXPENSE", frozenset({"M_NONCURRENT", "M_TAX"}))
    assert classify_pair(deferred_tax, noncurrent_tax) == UNRELATED
