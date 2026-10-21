"""Equivalence ranking: renamed and extension concepts share atom coordinates."""

from __future__ import annotations

from edgar_sec.engine.xbrl.normalize.decomposer import decompose_concept
from edgar_sec.engine.xbrl.schema.atoms import Atom
from edgar_sec.engine.xbrl.solve.equivalence import (
    EXACT,
    NEAR,
    UNRELATED,
    classify_pair,
    presumed_atom,
    rank_equivalents,
)
from edgar_sec.engine.xbrl.taxonomy.domain import load_domain_taxonomy


def _atom(qname: str) -> Atom:
    tax = load_domain_taxonomy()
    assert tax.token_lexicon is not None
    atom, _, _, _ = decompose_concept(qname, tax.token_lexicon)
    return atom


def test_renamed_revenue_concepts_are_exact_equivalents() -> None:
    """The pre- and post-ASC-606 revenue names decompose to one atom."""
    pre_asc606 = _atom("us-gaap:Revenues")
    post_asc606 = _atom("us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax")
    assert classify_pair(pre_asc606, post_asc606) == EXACT


def test_extension_reconciliation_item_matches_us_gaap_atom() -> None:
    """A firm extension lands on the same coordinate as us-gaap siblings."""
    extension = _atom(
        "aapl:EffectiveIncomeTaxRateReconciliationImpactOfTheStateAidDecisionAmount"
    )
    standard = _atom(
        "us-gaap:EffectiveIncomeTaxRateReconciliationDispositionOfBusiness"
    )
    assert classify_pair(extension, standard) == EXACT


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
    target = Atom("H_REVENUE")
    candidates = (
        ("firm-b:SalesRevenueNet", Atom("H_REVENUE", frozenset({"M_SALES_GOODS"}))),
        (
            "firm-a:RevenueFromContractWithCustomerExcludingAssessedTax",
            Atom("H_REVENUE"),
        ),
        ("firm-c:CostOfRevenue", Atom("H_COST")),
    )
    ranked = rank_equivalents("firm-x:Revenues", target, candidates)
    assert [item.qname for item in ranked] == [
        "firm-a:RevenueFromContractWithCustomerExcludingAssessedTax",
        "firm-b:SalesRevenueNet",
    ]
    assert [item.tier for item in ranked] == [EXACT, NEAR]


def test_related_party_transactions_exact_across_firms() -> None:
    """Ford and Coca-Cola name the same related-party receivable differently."""
    ford = _atom("f:RelatedPartyTransactionFinanceReceivablesNet")
    coke = _atom("ko:RelatedPartyTransactionNetReceivablesDueFromRelatedParty")
    assert "M_RELATED_PARTY" in ford.modifiers
    assert classify_pair(ford, coke) == EXACT


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


def test_sibling_group_matches_subatomic_data() -> None:
    """The solver's sibling group mirrors the taxonomy data declaration."""
    import json

    from edgar_sec.engine.xbrl.paths import resolve_xbrl_paths
    from edgar_sec.engine.xbrl.solve.equivalence import SIBLING_GROUPS

    defs = json.loads(resolve_xbrl_paths().default_subatomic_modifiers_path.read_text())
    declared = {d["modifier_id"] for d in defs if d.get("sibling_group")}
    grouped = set().union(*SIBLING_GROUPS) if SIBLING_GROUPS else set()
    assert declared == grouped


def test_default_coordinates_match_subatomic_data() -> None:
    """Default entries mirror the data: axis is a declared sibling group."""
    import json

    from edgar_sec.engine.xbrl.paths import resolve_xbrl_paths

    defs = json.loads(resolve_xbrl_paths().default_subatomic_modifiers_path.read_text())
    by_id = {d["modifier_id"]: d for d in defs}
    tax = load_domain_taxonomy()
    signatures = set()
    axes = set()
    for entry in tax.default_coordinates:
        assert by_id[entry.presumed_modifier].get("sibling_group") == entry.axis
        group_members = {
            d["modifier_id"] for d in defs if d.get("sibling_group") == entry.axis
        }
        assert len(group_members) >= 2
        assert entry.signature not in signatures
        signatures.add(entry.signature)
        axes.add(entry.axis)
    assert axes == {"MATURITY_HORIZON"}


def _defaults():
    """The shipped defaults table, loaded through the domain taxonomy."""
    return load_domain_taxonomy().default_coordinates


def test_presumed_atom_applies_only_to_a_silent_signature() -> None:
    """Presumption fires on the bare identity and nowhere else."""
    defaults = _defaults()
    bare = _atom("us-gaap:AccountsPayable")
    assert presumed_atom(bare, defaults).modifiers == {
        "M_ACCOUNTS_PAYABLE",
        "M_CURRENT",
    }
    for stated in (
        "us-gaap:AccountsPayableCurrent",
        "us-gaap:AccountsPayableNoncurrent",
        "us-gaap:AccountsPayableCurrentAndNoncurrent",
    ):
        atom = _atom(stated)
        assert presumed_atom(atom, defaults) == atom
    compound = _atom("us-gaap:AccountsPayableAndOtherAccruedLiabilities")
    assert presumed_atom(compound, defaults) == compound
    debt = Atom("H_LIABILITY", frozenset({"M_DEBT"}))
    assert presumed_atom(debt, defaults) == debt


def test_bare_payable_ranks_current_first_and_long_term_after() -> None:
    """For a bare AP target the presumed-current match leads the near set."""
    defaults = _defaults()
    target = _atom("us-gaap:AccountsPayable")
    candidates = (
        ("firm-a:AccountsPayableLongTerm", _atom("firm-a:AccountsPayableLongTerm")),
        ("firm-b:AccountsPayableCurrent", _atom("firm-b:AccountsPayableCurrent")),
        ("firm-c:AccountsPayable", _atom("firm-c:AccountsPayable")),
    )
    ranked = rank_equivalents("firm-x:AccountsPayable", target, candidates, defaults)
    assert [item.qname for item in ranked] == [
        "firm-c:AccountsPayable",
        "firm-b:AccountsPayableCurrent",
        "firm-a:AccountsPayableLongTerm",
    ]
    assert [item.tier for item in ranked] == [EXACT, NEAR, NEAR]
    assert not any(item.via_default for item in ranked)
    assert ranked[1].modifier_distance == 0
    assert ranked[2].modifier_distance == 2


def test_default_mediated_match_is_flagged_and_ranked_last() -> None:
    """Bare AP reaches accrued-current only under presumption: via_default."""
    defaults = _defaults()
    target = _atom("us-gaap:AccountsPayable")
    accrued = _atom("us-gaap:AccruedLiabilitiesCurrent")
    current = _atom("us-gaap:AccountsPayableCurrent")
    assert classify_pair(target, accrued) == UNRELATED
    ranked = rank_equivalents(
        "firm-x:AccountsPayable",
        target,
        (
            ("firm-a:AccruedLiabilitiesCurrent", accrued),
            ("firm-b:AccountsPayableCurrent", current),
        ),
        defaults,
    )
    assert [item.qname for item in ranked] == [
        "firm-b:AccountsPayableCurrent",
        "firm-a:AccruedLiabilitiesCurrent",
    ]
    assert ranked[0].via_default is False
    assert ranked[1].tier == NEAR and ranked[1].via_default is True


def test_explicit_horizon_swap_is_never_default_mediated() -> None:
    """LongTerm vs Current is an evidenced sibling swap, defaults or not."""
    defaults = _defaults()
    target = _atom("us-gaap:AccountsPayableLongTerm")
    candidate = _atom("us-gaap:AccountsPayableCurrent")
    ranked = rank_equivalents(
        "firm-x:AccountsPayableLongTerm",
        target,
        (("firm-a:AccountsPayableCurrent", candidate),),
        defaults,
    )
    assert len(ranked) == 1
    assert ranked[0].tier == NEAR and ranked[0].via_default is False


def test_identity_without_default_stays_equidistant() -> None:
    """Bare debt has no default: both horizon portions rank at distance one."""
    defaults = _defaults()
    target = Atom("H_LIABILITY", frozenset({"M_DEBT"}))
    candidates = (
        ("firm-a:DebtCurrent", Atom("H_LIABILITY", frozenset({"M_DEBT", "M_CURRENT"}))),
        (
            "firm-b:DebtNoncurrent",
            Atom("H_LIABILITY", frozenset({"M_DEBT", "M_NONCURRENT"})),
        ),
    )
    ranked = rank_equivalents("firm-x:Debt", target, candidates, defaults)
    assert [item.tier for item in ranked] == [NEAR, NEAR]
    assert [item.modifier_distance for item in ranked] == [1, 1]
    assert not any(item.via_default for item in ranked)


def test_dual_horizon_names_suppress_defaults_and_are_not_swaps() -> None:
    """Dual-horizon atoms are explicit evidence against each single sibling."""
    defaults = _defaults()
    dual = _atom("us-gaap:AccountsPayableCurrentAndNoncurrent")
    assert presumed_atom(dual, defaults) == dual
    for sibling in (
        "us-gaap:AccountsPayableCurrent",
        "us-gaap:AccountsPayableNoncurrent",
    ):
        assert classify_pair(dual, _atom(sibling)) == NEAR
    portion = _atom("us-gaap:LongTermDebtCurrent")
    assert presumed_atom(portion, defaults) == portion
    assert classify_pair(portion, _atom("us-gaap:DebtCurrent")) == NEAR


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
