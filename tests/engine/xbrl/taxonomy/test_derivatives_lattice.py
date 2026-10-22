"""Tests for derivative coordinates and generic taxonomy declarations."""

from edgar_sec.engine.xbrl.taxonomy.domain import load_domain_taxonomy
from edgar_sec.engine.xbrl.normalize.decomposer import decompose_concept
from edgar_sec.engine.xbrl.schema.atoms import Atom


def test_derivative_risk_structure_and_hedge_axes_are_orthogonal() -> None:
    taxonomy = load_domain_taxonomy()
    instruments = {edge.child_instrument: edge for edge in taxonomy.instruments_dag}

    ir_swap = instruments["InterestRateSwapMember"]
    assert (ir_swap.underlying_risk, ir_swap.contract_structure) == ("IR", "SWAP")
    assert ir_swap.hedge_designation == "ALL_DESIGNATION"
    assert not taxonomy.is_instrument_subtype(
        "InterestRateSwapMember", "ForwardContractMember"
    )

    commodity_option = instruments["CommodityOptionMember"]
    assert (commodity_option.underlying_risk, commodity_option.contract_structure) == (
        "CM",
        "OPTION",
    )
    assert taxonomy.is_instrument_subtype("CommodityOptionMember", "OptionMember")
    assert taxonomy.is_instrument_subtype("CommodityOptionMember", "DerivativeMember")

    assert instruments["SwaptionMember"].contract_structure == "OPTION"
    assert instruments["CrossCurrencySwapMember"].underlying_risk == "FX"
    assert instruments["EquityDerivativeMember"].underlying_risk == "EQ"
    assert instruments["CommodityContractMember"].underlying_risk == "CM"

    hedge_modifiers = {
        modifier.modifier_id
        for modifier in taxonomy.subatomic_modifiers
        if modifier.category == "HEDGE_DESIGNATION"
    }
    assert hedge_modifiers == {
        "M_FAIR_VALUE_HEDGE",
        "M_CASH_FLOW_HEDGE",
        "M_NET_INVESTMENT_HEDGE",
        "M_UNDESIGNATED_ECONOMIC",
    }


def test_contract_structures_are_pairwise_exclusive() -> None:
    taxonomy = load_domain_taxonomy()
    structures = ("FORWARD", "FUTURES", "SWAP", "OPTION")

    for index, structure_a in enumerate(structures):
        for structure_b in structures[index + 1 :]:
            assert taxonomy.are_contract_structures_exclusive(structure_a, structure_b)


def test_compound_derivative_terms_factor_into_independent_coordinates() -> None:
    taxonomy = load_domain_taxonomy()
    assert taxonomy.token_lexicon is not None
    cases = {
        "DerivativeFXForwardAssets": {
            "H_ASSET",
            "M_DERIVATIVE",
            "M_RISK_FX",
            "M_FORWARD",
        },
        "DerivativeCommodityFuturesAssets": {
            "H_ASSET",
            "M_DERIVATIVE",
            "M_RISK_COMMODITY",
            "M_FUTURES",
        },
        "DerivativeInterestRateSwapLiabilities": {
            "H_LIABILITY",
            "M_DERIVATIVE",
            "M_RISK_IR",
            "M_SWAP",
        },
        "DerivativeEquityOptionAssets": {
            "H_ASSET",
            "M_DERIVATIVE",
            "M_RISK_EQUITY",
            "M_OPTION",
        },
        "DerivativeCreditDefaultSwapLiabilities": {
            "H_LIABILITY",
            "M_DERIVATIVE",
            "M_RISK_CREDIT",
            "M_SWAP",
        },
        "DerivativeInterestRateCapAssets": {
            "H_ASSET",
            "M_DERIVATIVE",
            "M_RISK_IR",
            "M_OPTION",
            "M_CAP_FLOOR_COLLAR",
        },
        "DerivativeInterestRateSwaptionAssets": {
            "H_ASSET",
            "M_DERIVATIVE",
            "M_RISK_IR",
            "M_OPTION",
            "M_SWAPTION",
        },
        "DerivativeCrossCurrencySwapLiabilities": {
            "H_LIABILITY",
            "M_DERIVATIVE",
            "M_RISK_FX",
            "M_SWAP",
            "M_CROSS_CURRENCY_SWAP",
        },
    }
    for concept, expected in cases.items():
        atom, residuals, _, _ = decompose_concept(concept, taxonomy.token_lexicon)
        assert residuals == ()
        assert {atom.head, *atom.modifiers} == expected

    fx_forward, _, _, _ = decompose_concept(
        "DerivativeFXForwardAssets", taxonomy.token_lexicon
    )
    assert fx_forward.is_a(Atom("H_ASSET", {"M_DERIVATIVE", "M_RISK_FX"}))
    assert fx_forward.is_a(Atom("H_ASSET", {"M_FORWARD"}))

    for modifier_id in ("M_FORWARD", "M_FUTURES", "M_SWAP"):
        modifier = taxonomy.modifier(modifier_id)
        assert modifier is not None
        assert not any(
            keyword in modifier.keywords
            for keyword in (
                "FXForward",
                "CommodityFutures",
                "IndexFutures",
                "InterestRateSwap",
                "BasisSwap",
                "CurrencySwap",
            )
        )


def test_generic_taxonomy_has_no_product_names_in_service_modifier() -> None:
    taxonomy = load_domain_taxonomy()
    service = taxonomy.modifier("M_SERVICE_CLOUD")
    assert service is not None
    assert "Office" not in service.keywords
    assert "Dynamics" not in service.keywords

    for modifier_id in (
        "M_PRE_PROVISION",
        "M_FINANCING_RECEIVABLE",
        "M_CREDIT_LOSS_PROVISION",
        "M_FULFILLMENT",
        "M_TECH_INFRA",
        "M_ACTIVISM_COSTS",
        "M_RISK_FX",
        "M_RISK_IR",
        "M_RISK_COMMODITY",
        "M_RISK_EQUITY",
        "M_RISK_CREDIT",
        "M_CAP_FLOOR_COLLAR",
        "M_SWAPTION",
        "M_CROSS_CURRENCY_SWAP",
        "M_NOTIONAL_AMOUNT",
        "M_COUNTERPARTY_NETTING",
        "M_CASH_COLLATERAL_OFFSET",
    ):
        assert taxonomy.modifier(modifier_id) is not None

    assert taxonomy.token_lexicon is not None
    entries = {entry.phrase: entry for entry in taxonomy.token_lexicon.entries}
    assert entries[("pre", "provision")].atom == "M_PRE_PROVISION"
    assert entries[("financing", "receivable")].head == "H_ASSET"
    assert "M_FINANCING_RECEIVABLE" in entries[("financing", "receivable")].carriage
