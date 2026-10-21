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


def test_number_words_become_indexicals_not_residuals() -> None:
    """Maturity siblings share one atom and differ only in num indexical."""
    tax = load_domain_taxonomy()
    assert tax.token_lexicon is not None

    five_atom, five_res, _, five_idx = decompose_concept(
        "us-gaap:LongTermDebtMaturitiesDueInFiveYears", tax.token_lexicon
    )
    three_atom, three_res, _, three_idx = decompose_concept(
        "us-gaap:LongTermDebtMaturitiesDueInThreeYears", tax.token_lexicon
    )
    assert five_atom == three_atom
    assert five_idx == ("num=5",)
    assert three_idx == ("num=3",)
    assert "Five" not in five_res
    assert "Three" not in three_res


def test_number_range_merges_into_one_indexical() -> None:
    """After Five Through Ten Years yields a single num=5..10 indexical."""
    tax = load_domain_taxonomy()
    assert tax.token_lexicon is not None

    _, _, _, indexicals = decompose_concept(
        "us-gaap:AvailableForSaleSecuritiesDebtMaturitiesAfterFiveThroughTenYearsAmortizedCost",
        tax.token_lexicon,
    )
    assert indexicals == ("num=5..10",)


def test_net_of_keeps_left_side_number_indexical() -> None:
    """A number left of a NET_OF operator survives in the indexicals."""
    tax = load_domain_taxonomy()
    assert tax.token_lexicon is not None

    expression = decompose_concept_expression(
        "us-gaap:RevenueFromFiveYearContractNetOfInterestExpense", tax.token_lexicon
    )
    assert expression.operator == "NET_OF"
    assert expression.indexicals == ("num=5",)


def test_ordinals_share_atom_and_differ_as_indexicals() -> None:
    """Ordinal maturity siblings: same atom, ord= indexicals carry the slot."""
    tax = load_domain_taxonomy()
    assert tax.token_lexicon is not None
    second = decompose_concept_expression(
        "us-gaap:ContractualObligationDueInSecondYear", tax.token_lexicon
    )
    fifth = decompose_concept_expression(
        "us-gaap:ContractualObligationDueInFifthYear", tax.token_lexicon
    )
    assert second.atom == fifth.atom
    assert second.indexicals == ("ord=2",)
    assert fifth.indexicals == ("ord=5",)
    assert "NUM" not in second.residuals


def test_counterparty_and_past_due_phrase_merges() -> None:
    """Third/Related Party and Past Due decompose as single modifiers."""
    tax = load_domain_taxonomy()
    assert tax.token_lexicon is not None
    third, _, _, _ = decompose_concept(
        "f:CreditFacilityGuaranteeByThirdPartyAmount", tax.token_lexicon
    )
    assert "M_THIRD_PARTY" in third.modifiers
    related, _, _, _ = decompose_concept(
        "f:RelatedPartyTransactionFinanceReceivablesNet", tax.token_lexicon
    )
    assert "M_RELATED_PARTY" in related.modifiers
    past_due, _, _, _ = decompose_concept(
        "jpm:FinancingReceivableNonaccrualPercentThirtyOrMoreDaysPastDue",
        tax.token_lexicon,
    )
    assert "M_PAST_DUE" in past_due.modifiers
    assert "M_MATURITY" not in past_due.modifiers
    maturity = decompose_concept_expression(
        "amzn:FinancingObligationsFutureMinimumPaymentsDueInFiveYears",
        tax.token_lexicon,
    )
    assert "M_MATURITY" in maturity.atom.modifiers
    assert "M_PAST_DUE" not in maturity.atom.modifiers
    assert maturity.indexicals == ("num=5",)


def test_mined_phrase_merges() -> None:
    """Disposal group, off-balance-sheet, AFS/HTM phrases claim as units."""
    tax = load_domain_taxonomy()
    assert tax.token_lexicon is not None
    disposal, _, _, _ = decompose_concept(
        "apd:DisposalGroupIncludingDiscontinuedOperationApproximateAnnualSales",
        tax.token_lexicon,
    )
    assert "M_DISPOSAL_GROUP" in disposal.modifiers
    off_bs, _, _, _ = decompose_concept(
        "jpm:FinancingReceivableAndDebtSecuritiesAllowanceForCreditLoss"
        "AndOffBalanceSheetCreditLossLiability",
        tax.token_lexicon,
    )
    assert "M_OFF_BALANCE_SHEET" in off_bs.modifiers
    afs_htm, _, _, _ = decompose_concept(
        "jpm:DebtSecuritiesAvailableForSaleAndHeldToMaturityAccruedInterest"
        "AfterAllowanceForCreditLoss",
        tax.token_lexicon,
    )
    assert "M_AVAILABLE_FOR_SALE" in afs_htm.modifiers
    assert "M_HELD_TO_MATURITY" in afs_htm.modifiers


def test_fiscal_year_is_an_indexical_not_a_modifier() -> None:
    """Fiscal Year scopes a concept (indexical) instead of qualifying it."""
    tax = load_domain_taxonomy()
    assert tax.token_lexicon is not None
    expr = decompose_concept_expression(
        "cat:DefinedBenefitPlanHealthCareCostTrendRateAssumedForCurrentFiscalYear",
        tax.token_lexicon,
    )
    assert "FISCAL_YEAR" in expr.indexicals
    assert "M_MATURITY" not in expr.atom.modifiers


def test_fair_value_level_rides_the_number_grammar() -> None:
    """Level 3 decomposes as M_FAIR_VALUE with the level as num= indexical."""
    tax = load_domain_taxonomy()
    assert tax.token_lexicon is not None
    expr = decompose_concept_expression(
        "us-gaap:DefinedBenefitPlanPlanAssetsLevel3ReconciliationDecreaseForSale",
        tax.token_lexicon,
    )
    assert "M_FAIR_VALUE" in expr.atom.modifiers
    assert "M_PENSION_DEFINED_BENEFIT" in expr.atom.modifiers
    assert expr.indexicals == ("num=3",)


def test_fused_longterm_spelling_keeps_the_stated_override() -> None:
    """The fused Longterm spelling states the same override as Long Term."""
    tax = load_domain_taxonomy()
    assert tax.token_lexicon is not None
    fused, _, _, _ = decompose_concept(
        "us-gaap:AccountsPayableLongterm", tax.token_lexicon
    )
    spelled, _, _, _ = decompose_concept(
        "us-gaap:AccountsPayableLongTerm", tax.token_lexicon
    )
    assert fused == spelled
    assert fused.modifiers == frozenset({"M_ACCOUNTS_PAYABLE", "M_NONCURRENT"})


def test_due_windows_derive_bucket_horizons() -> None:
    """Due-in and due-within windows derive the bucket horizon arithmetically."""
    tax = load_domain_taxonomy()
    assert tax.token_lexicon is not None
    cases = {
        "us-gaap:LongTermDebtMaturitiesDueInFiveYears": "M_NONCURRENT",
        "us-gaap:ContractualObligationDueInSecondYear": "M_NONCURRENT",
        "us-gaap:AccrualForEnvironmentalLossContingenciesUndiscountedDueWithinOneYear": "M_CURRENT",
    }
    for qname, expected in cases.items():
        expression = decompose_concept_expression(qname, tax.token_lexicon)
        assert expression.derived_horizon == expected, qname


def test_schedule_pair_shares_atom_but_derives_opposite_horizons() -> None:
    """NextTwelveMonths vs AfterYearFive: one atom, opposite derivations."""
    tax = load_domain_taxonomy()
    assert tax.token_lexicon is not None
    soon = decompose_concept_expression(
        "us-gaap:LongTermDebtMaturitiesRepaymentsOfPrincipalInNextTwelveMonths",
        tax.token_lexicon,
    )
    later = decompose_concept_expression(
        "us-gaap:LongTermDebtMaturitiesRepaymentsOfPrincipalAfterYearFive",
        tax.token_lexicon,
    )
    assert soon.atom == later.atom
    assert soon.derived_horizon == "M_CURRENT"
    assert later.derived_horizon == "M_NONCURRENT"


def test_tenor_and_classification_compose_without_derivation() -> None:
    """Tenor alone derives nothing; an explicit classification word stands."""
    tax = load_domain_taxonomy()
    assert tax.token_lexicon is not None
    composed = decompose_concept_expression(
        "us-gaap:FiveYearLoanCurrent", tax.token_lexicon
    )
    assert composed.derived_horizon is None
    assert composed.atom.modifiers == frozenset({"M_CURRENT", "M_MATURITY"})
    tenor_only = decompose_concept_expression("us-gaap:FiveYearLoan", tax.token_lexicon)
    assert tenor_only.derived_horizon is None
    borrowings = decompose_concept_expression(
        "us-gaap:ShortTermBorrowings", tax.token_lexicon
    )
    assert borrowings.derived_horizon is None
    assert "M_CURRENT" in borrowings.atom.modifiers
