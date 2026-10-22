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


def test_renamed_revenue_concepts_are_near_equivalents() -> None:
    """Post-ASC-606 revenue decomposes compositionally: subsumption NEAR.

    Re-adjudicated in Phase 0: the former EXACT was a whole-phrase artifact.
    """
    pre_asc606 = _atom("us-gaap:Revenues")
    post_asc606 = _atom("us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax")
    assert classify_pair(pre_asc606, post_asc606) == NEAR


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
        "firm-a:Revenues": "equality",
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
    assert ranked[0].tier == EXACT and ranked[0].direction == ""


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


def test_rank_equivalents_orders_bac_derivative_pool_by_residuals() -> None:
    """The XVA name's four intent residuals rank it behind the headline."""
    target = _atom("us-gaap:DerivativeAssets")
    xva = "bac:DerivativeFundingRiskValuationAdjustmentDerivativeAssets"
    candidates = (
        (xva, _atom(xva)),
        ("us-gaap:DerivativeAssets", target),
    )
    counts = {"us-gaap:DerivativeAssets": (0, 0), xva: (4, 4)}
    ranked = rank_equivalents(
        "firm-x:DerivativeAssets", target, candidates, residual_counts=counts
    )
    assert [item.qname for item in ranked] == ["us-gaap:DerivativeAssets", xva]
    assert [item.tier for item in ranked] == [EXACT, EXACT]


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


def test_via_default_rule_overrides_the_presumed_classification() -> None:
    """A default-mediated NEAR reports via_default, not its presumed rule."""
    defaults = _defaults()
    target = _atom("us-gaap:AccountsPayable")
    ranked = rank_equivalents(
        "firm-x:AccountsPayable",
        target,
        (
            ("firm-a:AccountsPayableCurrent", _atom("us-gaap:AccountsPayableCurrent")),
            (
                "firm-b:AccruedLiabilitiesCurrent",
                _atom("us-gaap:AccruedLiabilitiesCurrent"),
            ),
        ),
        defaults,
    )
    rules = {item.qname: item.rule for item in ranked}
    assert rules == {
        "firm-a:AccountsPayableCurrent": "single_modifier_difference",
        "firm-b:AccruedLiabilitiesCurrent": "via_default",
    }
    assert ranked[-1].via_default is True


def test_declared_sibling_groups_reproduce_default_outcomes() -> None:
    """Declared JSON groups drive identical rankings and presumptions."""
    from edgar_sec.engine.xbrl.solve.equivalence import SIBLING_GROUPS

    tax = load_domain_taxonomy()
    declared = tax.sibling_groups
    assert {(g.group, frozenset(g.members)) for g in declared} == {
        (g.group, frozenset(g.members)) for g in SIBLING_GROUPS
    }

    defaults = _defaults()
    target = _atom("us-gaap:AccountsPayable")
    candidates = (
        ("firm-a:AccountsPayableCurrent", _atom("us-gaap:AccountsPayableCurrent")),
        (
            "firm-b:AccruedLiabilitiesCurrent",
            _atom("us-gaap:AccruedLiabilitiesCurrent"),
        ),
        ("firm-c:AccountsPayableLongTerm", _atom("us-gaap:AccountsPayableLongTerm")),
    )
    by_default = rank_equivalents(
        "firm-x:AccountsPayable", target, candidates, defaults
    )
    by_declared = rank_equivalents(
        "firm-x:AccountsPayable", target, candidates, defaults, sibling_groups=declared
    )
    assert by_declared == by_default
    assert presumed_atom(target, defaults, sibling_groups=declared) == presumed_atom(
        target, defaults
    )

    afs = _atom(
        "us-gaap:DebtSecuritiesAvailableForSaleMaturityAfter10YearsWeightedAverageYield"
    )
    htm = _atom(
        "us-gaap:DebtSecuritiesHeldToMaturityMaturityAfter10YearsWeightedAverageYield"
    )
    swapped = rank_equivalents(
        "firm-x:Afs", afs, (("firm-a:Htm", htm),), sibling_groups=declared
    )
    assert swapped[0].tier == NEAR and swapped[0].rule == "sibling_swap"


def _scope_key(scope) -> tuple:
    """Hashable scope shape: (heads, shared modifiers, exact) per context."""
    return tuple(
        (
            tuple(c.get("heads", ())) if isinstance(c, dict) else tuple(c.heads),
            tuple(
                c.get("shared_modifiers", ())
                if isinstance(c, dict)
                else c.shared_modifiers
            ),
            bool(c.get("shared_exact", False))
            if isinstance(c, dict)
            else c.shared_exact,
        )
        for c in scope
    )


def test_sibling_group_matches_subatomic_data() -> None:
    """Def memberships, the groups table, and the solver mirror agree."""
    import json

    from edgar_sec.engine.xbrl.paths import resolve_xbrl_paths
    from edgar_sec.engine.xbrl.solve.equivalence import SIBLING_GROUPS

    paths = resolve_xbrl_paths()
    defs = json.loads(paths.default_subatomic_modifiers_path.read_text())
    table = json.loads(paths.default_sibling_groups_path.read_text())
    declared = {
        (d["modifier_id"], group) for d in defs for group in d.get("sibling_groups", ())
    }
    tabled = {(member, g["group"]) for g in table for member in g["members"]}
    assert declared == tabled
    mirror = {(member, g.group) for g in SIBLING_GROUPS for member in g.members}
    assert mirror == tabled
    table_scopes = {g["group"]: _scope_key(g.get("scope", ())) for g in table}
    mirror_scopes = {g.group: _scope_key(g.scope) for g in SIBLING_GROUPS}
    assert mirror_scopes == table_scopes


def test_default_coordinates_match_subatomic_data() -> None:
    """Default entries mirror the data: the axis is among the def's groups."""
    import json

    from edgar_sec.engine.xbrl.paths import resolve_xbrl_paths

    defs = json.loads(resolve_xbrl_paths().default_subatomic_modifiers_path.read_text())
    by_id = {d["modifier_id"]: d for d in defs}
    tax = load_domain_taxonomy()
    signatures = set()
    axes = set()
    for entry in tax.default_coordinates:
        assert entry.axis in by_id[entry.presumed_modifier].get("sibling_groups", [])
        group_members = {
            d["modifier_id"] for d in defs if entry.axis in d.get("sibling_groups", [])
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


def test_anticipated_noncurrent_payable_is_exact_and_default_proof() -> None:
    """The unattested LiabilitiesLongTerm name: exact kin, default-proof."""
    defaults = _defaults()
    anticipated = _atom("us-gaap:AccountsPayableLiabilitiesLongTerm")
    assert (
        classify_pair(anticipated, _atom("us-gaap:AccountsPayableNoncurrent")) == EXACT
    )
    assert classify_pair(anticipated, _atom("us-gaap:AccountsPayableLongTerm")) == EXACT
    assert presumed_atom(anticipated, defaults) == anticipated
    bare = _atom("us-gaap:AccountsPayable")
    assert classify_pair(anticipated, bare) == NEAR
    ranked = rank_equivalents(
        "us-gaap:AccountsPayableLiabilitiesLongTerm",
        anticipated,
        (
            ("firm-a:AccountsPayable", bare),
            ("firm-b:AccountsPayableCurrent", _atom("firm-b:AccountsPayableCurrent")),
        ),
        defaults,
    )
    assert [item.tier for item in ranked] == [NEAR, NEAR]
    assert not any(item.via_default for item in ranked)


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


def test_deferred_rollforward_ranks_behind_the_asc606_headline() -> None:
    """Claiming Deferred moves the rollforward to distance 2, headline 3."""
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
    rollforward = by_qname["msft:ContractWithCustomerLiabilityRevenueDeferred"]
    headline = by_qname["us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"]
    assert rollforward.modifier_distance == 2 and rollforward.rule == "subsumption"
    assert headline.modifier_distance == 3


def test_deferred_is_not_a_maturity_sibling() -> None:
    """A Deferred/Noncurrent-only difference never classifies by sibling swap."""
    deferred = Atom("H_LIABILITY", frozenset({"M_DEFERRED"}))
    noncurrent = Atom("H_LIABILITY", frozenset({"M_NONCURRENT"}))
    assert classify_pair(deferred, noncurrent) == UNRELATED
    deferred_tax = Atom("H_EXPENSE", frozenset({"M_DEFERRED", "M_TAX"}))
    noncurrent_tax = Atom("H_EXPENSE", frozenset({"M_NONCURRENT", "M_TAX"}))
    assert classify_pair(deferred_tax, noncurrent_tax) == UNRELATED


def _scoped_portion_group():
    """A synthetic TAX_PORTION-shaped group: scoped to the tax-expense frame."""
    from edgar_sec.engine.xbrl.taxonomy.heads_modifiers import (
        ScopeContext,
        SiblingGroup,
    )

    return SiblingGroup(
        "TAX_PORTION",
        ("M_CURRENT", "M_DEFERRED"),
        "compoundable",
        scope=(
            ScopeContext(
                heads=("H_EXPENSE",),
                shared_modifiers=("M_TAX",),
                shared_exact=True,
            ),
            ScopeContext(
                heads=("H_INCOME",),
                shared_modifiers=("M_RECONCILIATION", "M_TAX_INCOME"),
            ),
        ),
    )


def test_scoped_sibling_swap_fires_only_inside_its_scope() -> None:
    """A scoped group swaps on its named coordinates and nowhere else."""
    groups = (_scoped_portion_group(),)
    current = Atom("H_EXPENSE", frozenset({"M_CURRENT", "M_TAX"}))
    deferred = Atom("H_EXPENSE", frozenset({"M_DEFERRED", "M_TAX"}))
    ranked = rank_equivalents(
        "firm-x:Current",
        current,
        (("firm-a:Deferred", deferred),),
        sibling_groups=groups,
    )
    assert ranked[0].tier == NEAR and ranked[0].rule == "sibling_swap"

    off_head = Atom("H_LIABILITY", frozenset({"M_DEFERRED", "M_TAX"}))
    assert (
        rank_equivalents(
            "firm-x:Current",
            current,
            (("firm-a:Off", off_head),),
            sibling_groups=groups,
        )
        == ()
    )
    current_tax = Atom("H_LIABILITY", frozenset({"M_CURRENT", "M_TAX"}))
    assert (
        rank_equivalents(
            "firm-x:Current",
            current_tax,
            (("firm-a:Off", off_head),),
            sibling_groups=groups,
        )
        == ()
    )
    wide = Atom("H_EXPENSE", frozenset({"M_CURRENT", "M_TAX", "M_OCI"}))
    wide_deferred = Atom("H_EXPENSE", frozenset({"M_DEFERRED", "M_TAX", "M_OCI"}))
    assert (
        rank_equivalents(
            "firm-x:Wide",
            wide,
            (("firm-a:Wide", wide_deferred),),
            sibling_groups=groups,
        )
        == ()
    )
    recon_current = Atom(
        "H_INCOME",
        frozenset({"M_CURRENT", "M_RECONCILIATION", "M_TAX", "M_TAX_INCOME"}),
    )
    recon_deferred = Atom(
        "H_INCOME",
        frozenset({"M_DEFERRED", "M_RECONCILIATION", "M_TAX", "M_TAX_INCOME"}),
    )
    ranked = rank_equivalents(
        "firm-x:Recon",
        recon_current,
        (("firm-a:Recon", recon_deferred),),
        sibling_groups=groups,
    )
    assert ranked[0].tier == NEAR and ranked[0].rule == "sibling_swap"


def test_scoped_membership_cannot_leak_across_groups() -> None:
    """Deferred vs Noncurrent stays unrelated with both groups in play."""
    from edgar_sec.engine.xbrl.taxonomy.heads_modifiers import SiblingGroup

    groups = (
        _scoped_portion_group(),
        SiblingGroup("MATURITY_HORIZON", ("M_CURRENT", "M_NONCURRENT"), "compoundable"),
    )
    deferred_tax = Atom("H_EXPENSE", frozenset({"M_DEFERRED", "M_TAX"}))
    noncurrent_tax = Atom("H_EXPENSE", frozenset({"M_NONCURRENT", "M_TAX"}))
    assert (
        rank_equivalents(
            "firm-x:Deferred",
            deferred_tax,
            (("firm-a:Noncurrent", noncurrent_tax),),
            sibling_groups=groups,
        )
        == ()
    )


def test_tax_portion_pairs_are_sibling_swaps() -> None:
    """Current and deferred portions of income tax expense are near kin."""
    current = _atom("us-gaap:CurrentIncomeTaxExpenseBenefit")
    deferred = _atom("us-gaap:DeferredIncomeTaxExpenseBenefit")
    assert classify_pair(current, deferred) == NEAR
    ranked = rank_equivalents(
        "us-gaap:CurrentIncomeTaxExpenseBenefit",
        current,
        (("us-gaap:DeferredIncomeTaxExpenseBenefit", deferred),),
    )
    assert ranked[0].tier == NEAR and ranked[0].rule == "sibling_swap"
    for current_q, deferred_q in (
        (
            "asml:EffectiveIncomeTaxRateReconciliationPriorYearCurrentIncomeTaxesAmount",
            "asml:EffectiveIncomeTaxRateReconciliationPriorYearDeferredIncomeTaxesAmount",
        ),
        (
            "asml:EffectiveIncomeTaxRateReconciliationPriorYearCurrentIncomeTaxesPercent",
            "asml:EffectiveIncomeTaxRateReconciliationPriorYearDeferredIncomeTaxesPercent",
        ),
    ):
        assert classify_pair(_atom(current_q), _atom(deferred_q)) == NEAR


def test_tax_bearing_swap_shapes_outside_the_portion_scope_stay_unrelated() -> None:
    """Same swap shape, wrong coordinates: the scope refuses these pairs."""
    near_miss = (
        _atom("us-gaap:AccrualForTaxesOtherThanIncomeTaxesCurrent"),
        _atom("us-gaap:DeferredIncomeTaxesAndTaxCredits"),
    )
    assert classify_pair(*near_miss) == UNRELATED
    asset_acquisition = (
        _atom("bmy:AssetAcquisitionDeferredIncomeTaxLiability"),
        _atom("us-gaap:AccruedIncomeTaxesCurrent"),
    )
    assert classify_pair(*asset_acquisition) == UNRELATED
    revenue_shape = (
        _atom("asml:ContractWithCustomerAssetRevenueRecognizedDuringTheCurrentYear"),
        _atom("msft:ContractWithCustomerLiabilityRevenueDeferred"),
    )
    assert classify_pair(*revenue_shape) == UNRELATED


def test_corpus_deferred_noncurrent_shapes_stay_unrelated() -> None:
    """A corpus Deferred/Noncurrent pair is not a swap on any declared axis."""
    deferred = _atom("us-gaap:DeferredIncomeTaxLiabilities")
    noncurrent = _atom("alb:TaxIndemnificationLiabilityNoncurrent")
    assert deferred.modifiers == frozenset({"M_DEFERRED", "M_TAX"})
    assert noncurrent.modifiers == frozenset({"M_NONCURRENT", "M_TAX"})
    assert classify_pair(deferred, noncurrent) == UNRELATED


def test_presumed_atom_axis_resolution_is_name_aware() -> None:
    """The silence test consults the named axis, not the first group found."""
    from edgar_sec.engine.xbrl.taxonomy.defaults import DefaultCoordinate
    from edgar_sec.engine.xbrl.taxonomy.heads_modifiers import SiblingGroup

    entry = DefaultCoordinate(
        head="H_EXPENSE",
        identity_modifiers=("M_DEFERRED",),
        axis="MATURITY_HORIZON",
        presumed_modifier="M_CURRENT",
        rationale="Synthetic: portion identity, horizon default.",
        attestation_class="anticipated",
    )
    groups = (
        _scoped_portion_group(),
        SiblingGroup("MATURITY_HORIZON", ("M_CURRENT", "M_NONCURRENT"), "compoundable"),
    )
    atom = Atom("H_EXPENSE", frozenset({"M_DEFERRED"}))
    presumed = presumed_atom(atom, (entry,), sibling_groups=groups)
    assert presumed.modifiers == frozenset({"M_DEFERRED", "M_CURRENT"})


def _typed_atom(qname: str, item_type: str) -> Atom:
    from edgar_sec.engine.xbrl.schema.models import ConceptDeclaration
    from edgar_sec.engine.xbrl.solve.tokenizer import ConceptTokenizer

    declaration = ConceptDeclaration(
        concept_qname=qname, name=qname.partition(":")[2], item_type=item_type
    )
    return ConceptTokenizer(load_domain_taxonomy()).tokenize(qname, declaration).atom


def test_text_barrier_kills_a_false_exact() -> None:
    """Typed text vs a bare numeric atom: UNRELATED where untyped was EXACT."""
    text = _typed_atom(
        "all:CapitalStructureDisclosureTextBlock", "dtr-types:textBlockItemType"
    )
    numeric = _atom("adm:Biodieseltaxcredit")
    assert text == Atom("H_UNKNOWN", frozenset({"M_TEXT_NODE"}))
    assert numeric == Atom("H_UNKNOWN")
    assert (
        classify_pair(_atom("all:CapitalStructureDisclosureTextBlock"), numeric)
        == EXACT
    )
    assert classify_pair(text, numeric) == UNRELATED
    assert classify_pair(numeric, text) == UNRELATED


def test_text_barrier_rule_shapes() -> None:
    """One-modifier difference and subsumption shapes both hit the barrier."""
    text = Atom("H_DISCLOSURE", frozenset({"M_TEXT_NODE"}))
    bare = Atom("H_DISCLOSURE")
    assert classify_pair(text, bare) == UNRELATED
    wider_text = Atom("H_DISCLOSURE", frozenset({"M_TEXT_NODE", "M_SEGMENT"}))
    assert wider_text.is_a(bare)
    assert classify_pair(wider_text, bare) == UNRELATED


def test_text_pairs_classify_by_the_ordinary_rules() -> None:
    """Text↔text: the coordinate cancels; renamed policy notes still match."""
    pld = _typed_atom(
        "pld:NoncontrollingInterestsPolicyTextBlock", "dtr-types:textBlockItemType"
    )
    tsla = _typed_atom(
        "tsla:NoncontrollingInterestsPolicyTextBlock", "dtr-types1:textBlockItemType"
    )
    assert "M_TEXT_NODE" in pld.modifiers and "M_TEXT_NODE" in tsla.modifiers
    assert classify_pair(pld, tsla) == EXACT
    cycle = _typed_atom(
        "ba:OperatingCyclePolicyTextBlock", "dtr-types1:textBlockItemType"
    )
    structure = _typed_atom(
        "all:CapitalStructureDisclosureTextBlock", "dtr-types:textBlockItemType"
    )
    assert classify_pair(cycle, structure) == NEAR


def test_text_coordinate_never_enters_presumption() -> None:
    """No default signature names the coordinate; presumption leaves it alone."""
    tax = load_domain_taxonomy()
    for entry in tax.default_coordinates:
        assert "M_TEXT_NODE" not in entry.identity_modifiers
        assert entry.presumed_modifier != "M_TEXT_NODE"
    groups = tuple(tax.sibling_groups) or None
    for entry in tax.default_coordinates:
        text_atom = Atom(
            entry.head, frozenset(entry.identity_modifiers) | {"M_TEXT_NODE"}
        )
        assert presumed_atom(text_atom, tax.default_coordinates, groups) == text_atom
