"""Equivalence wordforms: wordform twins, marker pairs, head distances."""

from __future__ import annotations

from edgar_sec.engine.xbrl.schema.atoms import Atom
from edgar_sec.engine.xbrl.solve.concepts.equivalence import (
    EXACT,
    NEAR,
    UNRELATED,
    classify_ladder_pair,
    classify_pair,
)
from edgar_sec.engine.xbrl.taxonomy.domain import load_domain_taxonomy
from tests.engine.xbrl.solve.concepts.equivalence_support import _atom


def test_wordform_twins_classify_exact() -> None:
    """Singular and plural forms of one novel line share an atom: EXACT."""
    for singular, plural in (
        ("ext:SettlementOfInsuranceClaims", "ext:SettlementsOfInsuranceClaims"),
        ("ext:IssuanceOfSolarBonds", "ext:IssuancesOfSolarBonds"),
        ("ext:TransferOfSolarAssets", "ext:TransfersOfSolarAssets"),
        ("ext:SolarWarrantyAccrual", "ext:SolarWarrantyAccruals"),
    ):
        assert classify_pair(_atom(singular), _atom(plural)) == EXACT


def test_gain_from_and_postfix_twins_classify_exact() -> None:
    """From and postfix twins share their On twins' atoms: EXACT."""
    for from_form, on_form in (
        (
            "ext:GainFromDisposalOfSolarGenerationEquipment",
            "ext:GainOnDisposalOfSolarGenerationEquipment",
        ),
        (
            "ext:LossFromSaleOfSolarGenerationEquipment",
            "ext:LossOnSaleOfSolarGenerationEquipment",
        ),
        (
            "ext:SolarGenerationEquipmentDisposalGain",
            "ext:GainOnDisposalOfSolarGenerationEquipment",
        ),
        (
            "ext:GainArisingFromSaleOfSolarGenerationEquipment",
            "ext:GainOnSaleOfSolarGenerationEquipment",
        ),
    ):
        assert classify_pair(_atom(from_form), _atom(on_form)) == EXACT


def test_gain_plural_and_remaining_from_twins_classify_exact() -> None:
    """Plural postfix and From-Disposals/Derecognition twins: EXACT."""
    for from_form, on_form in (
        (
            "ext:SolarGenerationEquipmentDisposalGains",
            "ext:GainOnDisposalOfSolarGenerationEquipment",
        ),
        (
            "ext:GainFromDisposalsOfSolarGenerationEquipment",
            "ext:GainOnDisposalOfSolarGenerationEquipment",
        ),
        (
            "ext:GainFromDerecognitionOfSolarGenerationEquipment",
            "ext:GainOnDisposalOfSolarGenerationEquipment",
        ),
        (
            "ext:LossFromDerecognitionOfSolarGenerationEquipment",
            "ext:LossOnDisposalOfSolarGenerationEquipment",
        ),
    ):
        assert classify_pair(_atom(from_form), _atom(on_form)) == EXACT


def test_gross_unrealized_side_twins_classify_near_by_swap() -> None:
    """Gross unrealized sides are NEAR by sibling swap, never EXACT."""
    tax = load_domain_taxonomy()

    def classify(target: str, candidate: str):
        return classify_ladder_pair(
            _atom(target),
            _atom(candidate),
            tax.default_coordinates,
            tuple(tax.sibling_groups),
            relations=tax.atom_relations,
        )

    gain = (
        "us-gaap:AvailableForSaleDebtSecuritiesAccumulatedGrossUnrealizedGainBeforeTax"
    )
    loss = (
        "us-gaap:AvailableForSaleDebtSecuritiesAccumulatedGrossUnrealizedLossBeforeTax"
    )
    combined = "us-gaap:DebtSecuritiesAvailableForSaleAccumulatedGrossUnrealizedGainLossBeforeTax"

    result = classify(gain, loss)
    assert result.tier == NEAR
    assert result.rule == "sibling_swap"

    for side in (gain, loss):
        result = classify(side, combined)
        assert result.tier == NEAR
        assert result.rule == "single_modifier_difference"

    bare = classify(
        "us-gaap:AvailableForSaleDebtSecuritiesGrossUnrealizedGain",
        "us-gaap:AvailableForSaleDebtSecuritiesGrossUnrealizedLoss",
    )
    assert bare.tier == NEAR
    assert bare.rule == "sibling_swap"


def test_reversal_bare_pair_is_one_marker_apart() -> None:
    """The bare impairment pair separates by exactly the reversal marker."""
    tax = load_domain_taxonomy()
    plain = _atom("acme:ImpairmentLoss")
    reversal = _atom("acme:ReversalOfImpairmentLoss")
    assert plain.modifiers == {"M_IMPAIRMENT"}
    assert reversal.modifiers == {"M_IMPAIRMENT", "M_REVERSAL"}
    for target, candidate in ((plain, reversal), (reversal, plain)):
        result = classify_ladder_pair(
            target,
            candidate,
            tax.default_coordinates,
            tuple(tax.sibling_groups),
            relations=tax.atom_relations,
        )
        assert result.tier == NEAR
        assert result.rule == "single_modifier_difference"


def test_declared_and_paid_dividends_are_one_marker_apart() -> None:
    """Declared and paid dividend lines separate by the declaration marker."""
    tax = load_domain_taxonomy()
    declared = _atom("acme:CashDividendsDeclared")
    paid = _atom("acme:CashDividendsPaid")
    assert declared.modifiers == {"M_DECLARATION", "M_DIVIDEND"}
    assert paid.modifiers == {"M_DIVIDEND"}
    result = classify_ladder_pair(
        declared,
        paid,
        tax.default_coordinates,
        tuple(tax.sibling_groups),
        relations=tax.atom_relations,
    )
    assert result.tier == NEAR
    assert result.rule == "single_modifier_difference"


def test_issuance_and_redemption_no_longer_classify_exact() -> None:
    """The issuance and redemption acts separate on the same instrument."""
    tax = load_domain_taxonomy()
    issuance = _atom("acme:IssuanceOfConvertibleNotes")
    redemption = _atom("acme:RedemptionOfConvertibleNotes")
    assert "M_ISSUANCE" in issuance.modifiers
    assert "M_REDEMPTION" in redemption.modifiers
    result = classify_ladder_pair(
        issuance,
        redemption,
        tax.default_coordinates,
        tuple(tax.sibling_groups),
        relations=tax.atom_relations,
    )
    assert result.tier == UNRELATED


def test_exercise_and_expiration_outcomes_swap_inside_scope() -> None:
    """Exercised and expired award counts swap; cash coordinates refuse."""
    tax = load_domain_taxonomy()
    exercised = _atom(
        "ifrs-full:NumberOfShareOptionsExercisedInSharebasedPaymentArrangement"
    )
    expired = _atom(
        "ifrs-full:NumberOfShareOptionsExpiredInSharebasedPaymentArrangement"
    )
    assert "M_EXERCISE" in exercised.modifiers
    assert "M_EXPIRATION" in expired.modifiers
    result = classify_ladder_pair(
        exercised,
        expired,
        tax.default_coordinates,
        tuple(tax.sibling_groups),
        relations=tax.atom_relations,
    )
    assert result.tier == NEAR
    assert result.rule == "sibling_swap"

    cash_exercise = Atom("H_CASH", frozenset({"M_EXERCISE"}))
    cash_expiration = Atom("H_CASH", frozenset({"M_EXPIRATION"}))
    refused = classify_ladder_pair(
        cash_exercise,
        cash_expiration,
        tax.default_coordinates,
        tuple(tax.sibling_groups),
        relations=tax.atom_relations,
    )
    assert refused.tier == UNRELATED


def test_favorable_and_unfavorable_sides_swap() -> None:
    """The off-market outcome pair separates by side, as siblings."""
    tax = load_domain_taxonomy()
    favorable = _atom("us-gaap:FavorableRegulatoryActionMember")
    unfavorable = _atom("us-gaap:UnfavorableRegulatoryActionMember")
    assert "V_FAVORABLE_SIDE" in favorable.modifiers
    assert "V_UNFAVORABLE_SIDE" in unfavorable.modifiers
    result = classify_ladder_pair(
        favorable,
        unfavorable,
        tax.default_coordinates,
        tuple(tax.sibling_groups),
        relations=tax.atom_relations,
    )
    assert result.tier == NEAR
    assert result.rule == "sibling_swap"


def test_dialect_bridge_refuses_a_purchase_side_collection_marker() -> None:
    """A purchase-side atom carrying the collection marker fails entry."""
    tax = load_domain_taxonomy()
    payments = Atom("H_CASH", frozenset({"M_INVESTMENT"}))
    clean = Atom("H_ASSET", frozenset({"M_FINANCIAL_INSTRUMENT", "M_PURCHASE"}))
    marked = Atom(
        "H_ASSET",
        frozenset({"M_FINANCIAL_INSTRUMENT", "M_PURCHASE", "M_COLLECTION"}),
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


def test_collection_and_sale_proceeds_carry_their_own_markers() -> None:
    """Collection and sale proceeds lines state distinct exit acts."""
    tax = load_domain_taxonomy()
    collection = _atom("us-gaap:ProceedsFromCollectionOfFinanceReceivables")
    sale = _atom("us-gaap:PremiumsReceivableProceedsFromSaleOfReceivables")
    assert collection.modifiers == {"M_COLLECTION", "M_FINANCING_RECEIVABLE"}
    assert sale.modifiers == {"M_SALE"}
    for target, candidate in ((collection, sale), (sale, collection)):
        result = classify_ladder_pair(
            target,
            candidate,
            tax.default_coordinates,
            tuple(tax.sibling_groups),
            relations=tax.atom_relations,
        )
        assert result.tier == UNRELATED
        assert result.via_bridge is False


def test_proceeds_borrowings_dialects_meet_on_the_cash_head() -> None:
    """The IFRS borrowings proceeds line meets its us-gaap issuance twin."""
    tax = load_domain_taxonomy()
    issuance = _atom("us-gaap:ProceedsFromIssuanceOfLongTermDebt")
    borrowings = _atom("ifrs-full:ProceedsFromNoncurrentBorrowings")
    for target, candidate in ((issuance, borrowings), (borrowings, issuance)):
        result = classify_ladder_pair(
            target,
            candidate,
            tax.default_coordinates,
            tuple(tax.sibling_groups),
            relations=tax.atom_relations,
        )
        assert result.tier == NEAR
        assert result.rule == "single_modifier_difference"
        assert result.modifier_distance == 1
        assert result.via_bridge is False


def test_payments_coordinate_squatters_leave_by_their_source_acts() -> None:
    """Annuities and sold-not-yet-purchased proceeds no longer equal payments."""
    tax = load_domain_taxonomy()
    payments = _atom("us-gaap:PaymentsToAcquireOtherInvestments")
    purchase = _atom(
        "ifrs-full:PurchaseOfFinancialInstrumentsClassifiedAsInvestingActivities"
    )
    squatters = (
        _atom("us-gaap:ProceedsFromAnnuitiesAndInvestmentCertificates"),
        _atom("us-gaap:InvestmentSoldNotYetPurchasedSaleProceeds"),
    )
    for squatter in squatters:
        for target, candidate in ((squatter, payments), (payments, squatter)):
            result = classify_ladder_pair(
                target,
                candidate,
                tax.default_coordinates,
                tuple(tax.sibling_groups),
                relations=tax.atom_relations,
            )
            assert result.tier == NEAR
            assert result.rule == "single_modifier_difference"
            assert result.via_bridge is False
        result = classify_ladder_pair(
            squatter,
            purchase,
            tax.default_coordinates,
            tuple(tax.sibling_groups),
            relations=tax.atom_relations,
        )
        assert result.tier == UNRELATED
        assert result.via_bridge is False


def test_head_mismatch_distance_uses_presumed_atoms_under_defaults() -> None:
    """A head-mismatched pair stays UNRELATED; its distance counts presumption."""
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
        SiblingGroup("MATURITY_HORIZON", ("M_CURRENT", "M_NONCURRENT"), "compoundable"),
    )
    target = Atom("H_EXPENSE", frozenset({"M_DEFERRED"}))
    candidate = Atom("H_ASSET", frozenset({"M_TAX"}))
    stated = classify_ladder_pair(target, candidate, sibling_groups=groups)
    assert stated.tier == UNRELATED
    assert stated.modifier_distance == 2
    presumed = classify_ladder_pair(target, candidate, (entry,), sibling_groups=groups)
    assert presumed.tier == UNRELATED
    assert presumed.rule == ""
    assert presumed.via_default is False
    assert presumed.via_filing_local is False
    assert presumed.via_bridge is False
    assert presumed.direction == ""
    assert presumed.modifier_distance == 3


def test_head_mismatch_distance_counts_placement_horizon() -> None:
    """A placement horizon presumed on one side enters the pair distance."""
    target = Atom("H_ASSET", frozenset({"M_TAX"}))
    candidate = Atom("H_LIABILITY", frozenset({"M_TAX"}))
    plain = classify_ladder_pair(target, candidate)
    assert plain.tier == UNRELATED
    assert plain.modifier_distance == 0
    placed = classify_ladder_pair(
        target, candidate, candidate_placement_horizon="M_CURRENT"
    )
    assert placed.tier == UNRELATED
    assert placed.via_filing_local is False
    assert placed.modifier_distance == 1


def test_head_mismatched_purchase_pair_still_reaches_the_bridge() -> None:
    """The purchase marker keeps a head-mismatched pair out of the fast exit."""
    from edgar_sec.engine.xbrl.schema.relations import AtomRelation, AtomRelationGraph

    payments = Atom("H_CASH", frozenset({"M_PPE_CAPEX"}))
    purchase = Atom("H_ASSET", frozenset({"M_PPE_CAPEX", "M_PURCHASE"}))
    edge = AtomRelation(
        edge_id="R_SYNTHETIC_DIALECT",
        relation_type="DIALECT_OF",
        source=payments,
        target=purchase,
    )
    graph = AtomRelationGraph((edge,))
    for target, candidate in ((payments, purchase), (purchase, payments)):
        result = classify_ladder_pair(target, candidate, relations=graph)
        assert result.tier == NEAR
        assert result.rule == "dialect_bridge"
        assert result.via_bridge is True
        assert result.modifier_distance == 0
