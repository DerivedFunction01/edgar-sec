"""Core decomposer tests: expressions, provenance, and NET_OF."""

import pytest

from edgar_sec.engine.xbrl.normalize.decomposer import (
    decompose_concept,
    decompose_concept_expression,
    is_noise_residual,
    residual_counts,
    split_camel_case,
)
from edgar_sec.engine.xbrl.taxonomy.domain import DomainTaxonomy


def test_residual_counts_split_intent_from_noise() -> None:
    """Digits, stopwords, and structural tokens are noise; the rest intent."""
    assert residual_counts(()) == (0, 0)
    assert residual_counts(("1",)) == (0, 1)
    assert residual_counts(("Schedule", "Of")) == (0, 2)
    assert residual_counts(("Deferred",)) == (1, 1)
    assert residual_counts(("Funding", "Risk", "Valuation", "Adjustment")) == (4, 4)
    assert is_noise_residual("Table") is True
    assert is_noise_residual("Adjustment") is False


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


def test_decompose_concept_expression_is_cached(tax: DomainTaxonomy) -> None:
    """Verify identical decomposition inputs return the cached expression."""
    assert tax.token_lexicon is not None
    first = decompose_concept_expression("us-gaap:Revenues", tax.token_lexicon)
    assert decompose_concept_expression("us-gaap:Revenues", tax.token_lexicon) is first


def test_plain_decomposition_computes_one_cover(
    tax: DomainTaxonomy,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A plain-path decomposition computes candidates and cover exactly once."""
    from edgar_sec.engine.xbrl.normalize.lexicon import TokenLexicon

    assert tax.token_lexicon is not None
    counts = {"candidates": 0, "select_cover": 0}
    real_candidates = TokenLexicon.candidates
    real_select_cover = TokenLexicon.select_cover

    def counting_candidates(self, tokens, evidence=None):
        counts["candidates"] += 1
        return real_candidates(self, tokens, evidence)

    def counting_select_cover(self, tokens, candidates=None, evidence=None):
        counts["select_cover"] += 1
        return real_select_cover(self, tokens, candidates, evidence)

    monkeypatch.setattr(TokenLexicon, "candidates", counting_candidates)
    monkeypatch.setattr(TokenLexicon, "select_cover", counting_select_cover)
    decompose_concept_expression.cache_clear()
    try:
        decompose_concept_expression("us-gaap:Revenues", tax.token_lexicon)
    finally:
        decompose_concept_expression.cache_clear()
    assert counts == {"candidates": 1, "select_cover": 1}


def test_subordinator_clause_boundary_splitting(tax: DomainTaxonomy) -> None:
    """Verify subordinate clause heads are demoted to modifiers."""
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


def test_scoped_modifier_claims_and_bounds_head_region(tax: DomainTaxonomy) -> None:
    """A scope-marker phrase claims its coordinate yet bounds the head region."""
    assert tax.token_lexicon is not None

    atom, _, _, _ = decompose_concept(
        "afrm:FinancingReceivableExcludingAccruedInterestCreditLossExpense"
        "ReversalExcludingCertainProvisions",
        tax.token_lexicon,
    )
    assert atom.head == "H_ASSET"
    assert "M_EXCLUDING" in atom.modifiers
    assert "M_INTEREST" in atom.modifiers


def test_archetype_decomposes_compositionally(tax: DomainTaxonomy) -> None:
    """The ASC-606 name decomposes token-by-token, with no whole-phrase entry."""
    assert tax.token_lexicon is not None

    atom, residuals, _, _ = decompose_concept(
        "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
        tax.token_lexicon,
    )
    assert atom.head == "H_REVENUE"
    assert atom.modifiers == frozenset({"M_CONTRACT_CUSTOMER", "M_PRETAX", "M_TAX"})
    assert residuals == ()


def test_net_of_expression_preserves_both_operand_atoms(tax: DomainTaxonomy) -> None:
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


def test_expression_matches_name_the_entries_that_fired(tax: DomainTaxonomy) -> None:
    """Provenance: the archetype's matches are its head and relation entries."""
    assert tax.token_lexicon is not None

    expression = decompose_concept_expression(
        "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
        tax.token_lexicon,
    )
    assert [(m.start, m.end) for m in expression.matches] == [(0, 5), (5, 8)]
    head_match, relation_match = expression.matches
    assert head_match.entry.phrase == (
        "revenue",
        "from",
        "contract",
        "with",
        "customer",
    )
    assert head_match.entry.claim == "head"
    assert head_match.entry.head == "H_REVENUE"
    assert relation_match.entry.phrase == ("excluding", "assessed", "tax")
    assert relation_match.entry.claim == "relation"
    assert relation_match.entry.relation == "EXCLUDING"


def test_net_of_expression_matches_carry_both_operands(tax: DomainTaxonomy) -> None:
    """NET_OF provenance spans both sides, in full-token coordinates."""
    assert tax.token_lexicon is not None

    expression = decompose_concept_expression(
        "us-gaap:AccumulatedOtherComprehensiveIncomeLossNetOfTax",
        tax.token_lexicon,
    )
    assert expression.operator == "NET_OF"
    phrases = [m.entry.phrase for m in expression.matches]
    assert phrases[0] == (
        "accumulated",
        "other",
        "comprehensive",
        "income",
        "loss",
    )
    assert ("net", "of") in phrases
    tax_matches = [m for m in expression.matches if m.entry.phrase == ("tax",)]
    assert [(m.start, m.end) for m in tax_matches] == [(7, 8)]
    assert all(
        expression.matches[i].start <= expression.matches[i + 1].start
        for i in range(len(expression.matches) - 1)
    )


def test_multi_operator_rejection_has_empty_provenance(tax: DomainTaxonomy) -> None:
    """A rejected multi-operator name carries no matches."""
    assert tax.token_lexicon is not None

    expression = decompose_concept_expression(
        "us-gaap:RevenuesNetOfInterestExpenseNetOfTax", tax.token_lexicon
    )
    assert expression.atom.head == "H_UNKNOWN"
    assert expression.matches == ()


def test_long_derivative_qnames_keep_instrument_and_offset_factors(
    tax: DomainTaxonomy,
) -> None:
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
