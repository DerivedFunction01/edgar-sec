"""Unit tests for compositional concept decomposer and sub-atomic parsing."""

from edgar_sec.engine.xbrl.normalize.decomposer import (
    decompose_concept,
    decompose_concept_expression,
    infer_semantic_frame,
    split_camel_case,
)
from edgar_sec.engine.xbrl.taxonomy.domain import load_domain_taxonomy


def test_split_camel_case() -> None:
    """Verify CamelCase splitting into individual tokens."""
    tokens = split_camel_case("RevenueFromContractWithCustomerExcludingAssessedTax")
    assert tokens == (
        "Revenue",
        "From",
        "Contract",
        "With",
        "Customer",
        "Excluding",
        "Assessed",
        "Tax",
    )
    assert split_camel_case("OperatingIncomeLoss") == (
        "Operating",
        "Income",
        "Loss",
    )
    assert split_camel_case("GrossProfit") == ("Gross", "Profit")


def test_subordinator_clause_boundary_splitting() -> None:
    """Verify subordinate clause heads are demoted to modifiers."""
    tax = load_domain_taxonomy()
    assert tax.token_lexicon is not None

    # Sale in HeldForDevelopmentAndSale is in subordinate clause; primary head is Asset
    atom, residuals, _, _ = decompose_concept(
        "us-gaap:InventoryRealEstateHeldForDevelopmentAndSale",
        tax.token_lexicon,
    )
    assert atom.head == "H_ASSET"
    assert "M_REAL_ESTATE" in atom.modifiers
    assert "M_HELD_FOR_SALE" in atom.modifiers

    # CostsApplicableToSales demotes Sales to modifier under head Cost
    cost_atom, _, _, _ = decompose_concept(
        "us-gaap:CostsApplicableToSales",
        tax.token_lexicon,
    )
    assert cost_atom.head == "H_COST"
    assert "M_SALES_GOODS" in cost_atom.modifiers


def test_net_of_expression_preserves_both_operand_atoms() -> None:
    tax = load_domain_taxonomy()
    assert tax.token_lexicon is not None

    expression = decompose_concept_expression(
        "us-gaap:RevenuesNetOfInterestExpense", tax.token_lexicon
    )
    atom, residuals, _, _ = decompose_concept(
        "us-gaap:RevenuesNetOfInterestExpense", tax.token_lexicon
    )
    assert expression.operator == "NET_OF"
    assert expression.operands[0].head == "H_REVENUE"
    assert expression.operands[1].head == "H_EXPENSE"
    assert "M_INTEREST" in expression.operands[1].modifiers
    assert expression.weights == (1.0, -1.0)
    assert atom.head == "H_REVENUE"
    assert "V_NET" in atom.modifiers
    assert residuals == ()

    for concept in (
        "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
        "us-gaap:DerivativeAssetFairValueGrossAssetIncludingNotSubjectToMasterNettingArrangement",
    ):
        expression = decompose_concept_expression(concept, tax.token_lexicon)
        assert expression.operator is None


def test_long_derivative_qnames_keep_instrument_and_offset_factors() -> None:
    tax = load_domain_taxonomy()
    assert tax.token_lexicon is not None
    concepts = {
        "us-gaap:DerivativeLiabilityFairValueGrossLiabilityIncludingNotSubjectToMasterNettingArrangement": {
            "H_LIABILITY",
            "M_DERIVATIVE",
            "M_FAIR_VALUE",
            "V_GROSS",
            "M_NOT_SUBJECT_TO_NETTING",
        },
        "us-gaap:DerivativeCollateralObligationToReturnCash": {
            "H_CASH",
            "M_DERIVATIVE",
            "M_CASH_COLLATERAL_OFFSET",
            "M_COLLATERAL_RETURN",
        },
        "us-gaap:DerivativeCollateralRightToReclaimCash": {
            "H_CASH",
            "M_DERIVATIVE",
            "M_CASH_COLLATERAL_OFFSET",
            "M_COLLATERAL_RECLAIM",
        },
    }

    for concept, expected in concepts.items():
        atom, residuals, _, _ = decompose_concept(concept, tax.token_lexicon)
        assert {atom.head, *atom.modifiers} == expected
        assert residuals == ()


def test_infer_semantic_frame_canonical_and_unseen() -> None:
    """Verify semantic frame extraction for canonical and unseen tags."""
    tax = load_domain_taxonomy()

    rev_frame = infer_semantic_frame(
        "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax", tax
    )
    assert rev_frame.prime_head == "H_REVENUE"
    assert rev_frame.recognition_book == "B_INCOME_STATEMENT"
    assert rev_frame.flow_stock == "FLOW"

    cogs_frame = infer_semantic_frame("us-gaap:CostOfGoodsAndServicesSold", tax)
    assert cogs_frame.prime_head == "H_COST"

    rd_frame = infer_semantic_frame("us-gaap:ResearchAndDevelopmentExpense", tax)
    assert rd_frame.prime_head == "H_EXPENSE"
    assert "M_RD" in rd_frame.modifiers

    # Unseen extension tag decomposes with residual tokens
    unseen_frame = infer_semantic_frame("msft:FooBarRevenueNet", tax)
    assert unseen_frame.prime_head == "H_REVENUE"
    assert unseen_frame.residual_tokens == ("Foo", "Bar")
