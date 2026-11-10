"""Unit tests for compositional concept decomposer and sub-atomic parsing."""

import pytest

from edgar_sec.engine.xbrl.normalize.decomposer import (
    decompose_concept,
    decompose_concept_expression,
    infer_semantic_frame,
    is_noise_residual,
    residual_counts,
    split_camel_case,
)
from edgar_sec.engine.xbrl.schema.models import ConceptDeclaration
from edgar_sec.engine.xbrl.taxonomy.domain import load_domain_taxonomy


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


def test_decompose_concept_expression_is_cached() -> None:
    """Verify identical decomposition inputs return the cached expression."""
    tax = load_domain_taxonomy()
    assert tax.token_lexicon is not None
    first = decompose_concept_expression("us-gaap:Revenues", tax.token_lexicon)
    assert decompose_concept_expression("us-gaap:Revenues", tax.token_lexicon) is first


def test_plain_decomposition_computes_one_cover(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A plain-path decomposition computes candidates and cover exactly once."""
    from edgar_sec.engine.xbrl.normalize.lexicon import TokenLexicon

    tax = load_domain_taxonomy()
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


def test_scoped_modifier_claims_and_bounds_head_region() -> None:
    """A scope-marker phrase claims its coordinate yet bounds the head region."""
    tax = load_domain_taxonomy()
    assert tax.token_lexicon is not None

    atom, _, _, _ = decompose_concept(
        "afrm:FinancingReceivableExcludingAccruedInterestCreditLossExpense"
        "ReversalExcludingCertainProvisions",
        tax.token_lexicon,
    )
    assert atom.head == "H_ASSET"
    assert "M_EXCLUDING" in atom.modifiers
    assert "M_INTEREST" in atom.modifiers


def test_archetype_decomposes_compositionally() -> None:
    """The ASC-606 name decomposes token-by-token, with no whole-phrase entry."""
    tax = load_domain_taxonomy()
    assert tax.token_lexicon is not None

    atom, residuals, _, _ = decompose_concept(
        "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
        tax.token_lexicon,
    )
    assert atom.head == "H_REVENUE"
    assert atom.modifiers == frozenset({"M_CONTRACT_CUSTOMER", "M_PRETAX", "M_TAX"})
    assert residuals == ()


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


def test_expression_matches_name_the_entries_that_fired() -> None:
    """Provenance: the archetype's matches are its head and relation entries."""
    tax = load_domain_taxonomy()
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


def test_net_of_expression_matches_carry_both_operands() -> None:
    """NET_OF provenance spans both sides, in full-token coordinates."""
    tax = load_domain_taxonomy()
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


def test_multi_operator_rejection_has_empty_provenance() -> None:
    """A rejected multi-operator name carries no matches."""
    tax = load_domain_taxonomy()
    assert tax.token_lexicon is not None

    expression = decompose_concept_expression(
        "us-gaap:RevenuesNetOfInterestExpenseNetOfTax", tax.token_lexicon
    )
    assert expression.atom.head == "H_UNKNOWN"
    assert expression.matches == ()


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
    afs_htm = decompose_concept_expression(
        "jpm:DebtSecuritiesAvailableForSaleAndHeldToMaturityAccruedInterest"
        "AfterAllowanceForCreditLoss",
        tax.token_lexicon,
    )
    assert "M_HELD_TO_MATURITY" in afs_htm.atom.modifiers
    assert "M_AVAILABLE_FOR_SALE" not in afs_htm.atom.modifiers
    assert any(
        operand.head == "H_ASSET" and "M_AVAILABLE_FOR_SALE" in operand.modifiers
        for operand in afs_htm.operands[1:]
    )


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


def test_anticipated_liabilities_infix_variants_share_attested_atoms() -> None:
    """Unattested Liabilities-infix payable names land on attested atoms."""
    tax = load_domain_taxonomy()
    assert tax.token_lexicon is not None
    infix, res, _, _ = decompose_concept(
        "us-gaap:AccountsPayableLiabilitiesLongTerm", tax.token_lexicon
    )
    assert res == ()
    for attested in (
        "us-gaap:AccountsPayableNoncurrent",
        "us-gaap:AccountsPayableLongTerm",
        "us-gaap:AccountsPayableLiabilitiesLongterm",
    ):
        atom, attested_res, _, _ = decompose_concept(attested, tax.token_lexicon)
        assert atom == infix and attested_res == ()
    current, _, _, _ = decompose_concept(
        "us-gaap:AccountsPayableLiabilitiesCurrent", tax.token_lexicon
    )
    plain_current, _, _, _ = decompose_concept(
        "us-gaap:AccountsPayableCurrent", tax.token_lexicon
    )
    assert current == plain_current
    bare_infix, _, _, _ = decompose_concept(
        "us-gaap:AccountsPayableLiabilities", tax.token_lexicon
    )
    bare, _, _, _ = decompose_concept("us-gaap:AccountsPayable", tax.token_lexicon)
    assert bare_infix == bare


def test_leading_long_term_on_payable_liabilities_is_tenor_not_horizon() -> None:
    """A leading Long Term is tenor (D8/B2): it states no horizon bucket."""
    tax = load_domain_taxonomy()
    assert tax.token_lexicon is not None
    atom, res, _, _ = decompose_concept(
        "us-gaap:LongTermAccountsPayableLiabilities", tax.token_lexicon
    )
    assert res == ()
    assert "M_MATURITY" in atom.modifiers
    assert "M_NONCURRENT" not in atom.modifiers
    assert "M_CURRENT" not in atom.modifiers


def test_repayment_of_deposits_decomposes_from_pieces() -> None:
    """Repayment + Of + the deposit phrase compose the cash-flow atom."""
    tax = load_domain_taxonomy()
    assert tax.token_lexicon is not None
    atom, res, _, _ = decompose_concept(
        "jpm:RepaymentOfInterestBearingDepositsInBanks", tax.token_lexicon
    )
    assert res == ()
    assert atom.head == "H_CASH"
    assert atom.modifiers == frozenset({"M_INTEREST"})
    reordered, _, _, _ = decompose_concept(
        "x:RepaymentOfDepositsInBanksInterestBearing", tax.token_lexicon
    )
    assert reordered == atom


def test_beneficial_interest_share_datum_decomposes_from_pieces() -> None:
    """Scoped Beneficial Interest + Shares compose the share datum."""
    tax = load_domain_taxonomy()
    assert tax.token_lexicon is not None
    atom, _, _, _ = decompose_concept(
        "pld:BeneficialInterestOfOutstandingSharesBySinglePersonOrPersonsActingAsGroup",
        tax.token_lexicon,
    )
    assert atom.head == "H_SHARE"
    assert atom.modifiers == frozenset()
    reordered, _, _, _ = decompose_concept(
        "pld:BeneficialInterestOfOutstandingSharesByPersonsActingAsGroupOrSinglePerson",
        tax.token_lexicon,
    )
    assert reordered == atom


def test_maximum_percentage_of_beneficial_interest_decomposes() -> None:
    """Maximum Percentage claims the rate head over the scoped subject."""
    tax = load_domain_taxonomy()
    assert tax.token_lexicon is not None
    atom, res, _, _ = decompose_concept(
        "pld:MaximumPercentageOfBeneficialInterestOfOutstandingShares",
        tax.token_lexicon,
    )
    assert res == ("Outstanding",)
    assert atom.head == "H_UNIT_RATE"
    assert atom.modifiers == frozenset({"M_PERCENT"})


def test_stock_conversion_rate_decomposes_from_pieces() -> None:
    """Conversion Of Stock + Conversion Rate compose the rate datum."""
    tax = load_domain_taxonomy()
    assert tax.token_lexicon is not None
    atom, res, _, _ = decompose_concept(
        "jpm:ConversionOfStockConversionRate", tax.token_lexicon
    )
    assert res == ()
    assert atom.head == "H_UNIT_RATE"
    assert atom.modifiers == frozenset()
    reordered, _, _, _ = decompose_concept("x:ConversionRateOfStock", tax.token_lexicon)
    assert reordered == atom


def test_conversion_rate_adjustment_amounts_keep_their_heads() -> None:
    """A Conversion Rate Adjustment names an amount, not the rate."""
    tax = load_domain_taxonomy()
    assert tax.token_lexicon is not None
    adjustment, _, _, _ = decompose_concept(
        "bmy:BusinessCombinationConsiderationTransferredConversionRateAdjustment",
        tax.token_lexicon,
    )
    assert adjustment.head == "H_CASH"


def test_decommissioning_fund_payments_decompose_from_pieces() -> None:
    """Payments To + the scoped ARO-purpose clause compose the atom."""
    tax = load_domain_taxonomy()
    assert tax.token_lexicon is not None
    atom, res, _, _ = decompose_concept(
        "us-gaap:PaymentsToInvestInDecommissioningFund", tax.token_lexicon
    )
    assert res == ()
    assert atom.head == "H_CASH"
    assert atom.modifiers == frozenset({"M_ARO_DECOMMISSIONING"})
    fronted, _, _, _ = decompose_concept(
        "x:InvestInDecommissioningFundPaymentsTo", tax.token_lexicon
    )
    assert fronted == atom


def test_insurance_contract_benefits_decompose_from_pieces() -> None:
    """The insurance-benefits head composes under the NET_OF tail."""
    tax = load_domain_taxonomy()
    assert tax.token_lexicon is not None
    atom, _, _, _ = decompose_concept(
        "all:AccidentAndHealthInsuranceContractBenefitsNetOfReinsuranceRecoveries",
        tax.token_lexicon,
    )
    assert atom.head == "H_EXPENSE"
    assert atom.modifiers == frozenset({"M_INSURANCE_PREMIUM", "V_NET"})
    swapped, _, _, _ = decompose_concept(
        "x:HealthAndAccidentInsuranceContractBenefitsNetOfReinsuranceRecoveries",
        tax.token_lexicon,
    )
    assert swapped == atom


def test_area_of_real_estate_property_decomposes_from_pieces() -> None:
    """Area before Of claims the measure head; Real Estate the domain."""
    tax = load_domain_taxonomy()
    assert tax.token_lexicon is not None
    atom, _, _, _ = decompose_concept(
        "us-gaap:AreaOfRealEstateProperty", tax.token_lexicon
    )
    assert atom.head == "H_UNIT_RATE"
    assert atom.modifiers == frozenset({"M_REAL_ESTATE"})
    reordered, _, _, _ = decompose_concept(
        "x:PropertyAreaOfRealEstate", tax.token_lexicon
    )
    assert reordered == atom


def test_area_head_claim_is_scoped_to_of_phrasings() -> None:
    """A bare Area token without Of stays unclaimed (no head capture)."""
    tax = load_domain_taxonomy()
    assert tax.token_lexicon is not None
    code, _, _, _ = decompose_concept("dei:CityAreaCode", tax.token_lexicon)
    assert code.head == "H_UNKNOWN"


def test_nuclear_fuel_amortization_decomposes_from_pieces() -> None:
    """Other Amortization claims the expense head over the subject."""
    tax = load_domain_taxonomy()
    assert tax.token_lexicon is not None
    atom, _, _, _ = decompose_concept(
        "nee:NuclearFuelAndOtherAmortization", tax.token_lexicon
    )
    assert atom.head == "H_EXPENSE"
    assert atom.modifiers == frozenset({"M_DEPR_AMORT"})
    fronted, _, _, _ = decompose_concept(
        "x:OtherAmortizationAndNuclearFuel", tax.token_lexicon
    )
    assert fronted == atom


def test_gains_losses_on_loans_held_for_sale_decomposes() -> None:
    """Gains + Losses On boundary + the loan phrase compose the atom."""
    tax = load_domain_taxonomy()
    assert tax.token_lexicon is not None
    atom, res, _, _ = decompose_concept(
        "bac:GainsLossesOnLoansHeldForSale", tax.token_lexicon
    )
    assert res == ()
    assert atom.head == "H_INCOME"
    assert atom.modifiers == frozenset({"M_FINANCING_RECEIVABLE", "M_PURPOSE_SALE"})
    fronted, _, _, _ = decompose_concept(
        "x:OnLoansHeldForSaleGainsLosses", tax.token_lexicon
    )
    assert fronted == atom


def test_repayment_head_claim_is_scoped_to_of_captions() -> None:
    """Schedule nouns named Repayment keep their balance-sheet heads."""
    tax = load_domain_taxonomy()
    assert tax.token_lexicon is not None
    installments, _, _, _ = decompose_concept(
        "alb:DebtInstrumentRepaymentInstallments", tax.token_lexicon
    )
    assert installments.head == "H_LIABILITY"
    early, _, _, _ = decompose_concept(
        "us-gaap:EarlyRepaymentOfSeniorDebt", tax.token_lexicon
    )
    assert early.head == "H_CASH"


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
    assert composed.atom.modifiers == frozenset({"M_CURRENT", "M_MATURITY", "M_LOAN"})
    tenor_only = decompose_concept_expression("us-gaap:FiveYearLoan", tax.token_lexicon)
    assert tenor_only.derived_horizon is None
    borrowings = decompose_concept_expression(
        "us-gaap:ShortTermBorrowings", tax.token_lexicon
    )
    assert borrowings.derived_horizon is None
    assert "M_CURRENT" in borrowings.atom.modifiers


def test_head_class_arbitration_prefers_primary_over_instrument() -> None:
    """A PRIMARY flow head beats an INSTRUMENT head in the same region (B2)."""
    taxonomy = load_domain_taxonomy()
    assert taxonomy.token_lexicon is not None
    atom, _, _, _ = decompose_concept(
        "us-gaap:InterestExpenseFederalFundsPurchased", taxonomy.token_lexicon
    )
    assert atom.head == "H_EXPENSE"
    assert atom.modifiers == frozenset({"M_DEBT", "M_INTEREST"})


def test_expression_records_relation_claims() -> None:
    """EXCLUDING joins the expression's relations with its operand atom."""
    taxonomy = load_domain_taxonomy()
    assert taxonomy.token_lexicon is not None
    expr = decompose_concept_expression(
        "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax",
        taxonomy.token_lexicon,
    )
    assert [kind for kind, _ in expr.relations] == ["EXCLUDING"]
    assert expr.relations[0][1].modifiers == frozenset({"M_TAX"})


def test_expression_carries_temporal_facet_and_derived_horizon() -> None:
    """The interval lives on the expression; the horizon derives from it."""
    taxonomy = load_domain_taxonomy()
    assert taxonomy.token_lexicon is not None
    expr = decompose_concept_expression(
        "us-gaap:LongTermDebtMaturitiesRepaymentsOfPrincipalInNextTwelveMonths",
        taxonomy.token_lexicon,
    )
    assert expr.temporal is not None
    assert (expr.temporal.lo_months, expr.temporal.hi_months) == (0, 12)
    assert expr.derived_horizon == "M_CURRENT"


def test_frame_carries_indexicals_and_temporal() -> None:
    """The semantic frame no longer discards indexicals or the interval."""
    taxonomy = load_domain_taxonomy()
    frame = infer_semantic_frame(
        "us-gaap:LongTermDebtMaturitiesRepaymentsOfPrincipalInNextTwelveMonths",
        taxonomy,
    )
    assert frame.temporal is not None
    assert frame.indexicals


def test_coexistence_admission_requires_a_declared_pair() -> None:
    """RR2: a suppressed candidate attributes only via a declared pair."""
    from edgar_sec.engine.xbrl.normalize.lexicon import LexiconEntry, TokenLexicon

    compound = LexiconEntry(
        ("property", "plant", "and", "equipment"),
        "modifier",
        atom="M_PPE_CAPEX",
    )
    tail = LexiconEntry(
        ("equipment", "disposals"),
        "head",
        head="H_CASH",
        claim_class="TAIL",
    )
    plain = TokenLexicon((compound, tail))
    atom, _, _, _ = decompose_concept("x:PropertyPlantAndEquipmentDisposals", plain)
    assert atom.head == "H_UNKNOWN"
    assert atom.modifiers == frozenset({"M_PPE_CAPEX"})
    declared = LexiconEntry(
        ("equipment", "disposals"),
        "head",
        head="H_CASH",
        claim_class="TAIL",
        coexists_with=("property plant and equipment",),
    )
    with_pair = TokenLexicon((compound, declared))
    atom2, _, _, _ = decompose_concept(
        "x:PropertyPlantAndEquipmentDisposals", with_pair
    )
    assert atom2.head == "H_CASH"


def test_requires_evidence_claim_never_fires() -> None:
    """Q6: an evidence-gated claim is inert while no evidence channel exists."""
    from edgar_sec.engine.xbrl.normalize.lexicon import LexiconEntry, TokenLexicon

    gated = LexiconEntry(
        ("impairment",),
        "head",
        head="H_EXPENSE",
        claim_class="PRIMARY",
        requires_evidence=True,
    )
    lex = TokenLexicon((gated,))
    atom, _, _, _ = decompose_concept("x:Impairment", lex)
    assert atom.head == "H_UNKNOWN"


def test_requires_evidence_claim_fires_when_satisfied() -> None:
    """Q6 twin: a satisfied evidence context lets the gated claim fire."""
    from edgar_sec.engine.xbrl.normalize.lexicon import (
        EvidenceContext,
        LexiconEntry,
        TokenLexicon,
    )

    gated = LexiconEntry(
        ("impairment",),
        "head",
        head="H_EXPENSE",
        claim_class="PRIMARY",
        requires_evidence=True,
    )
    lex = TokenLexicon((gated,))
    satisfied = EvidenceContext("0000000001-24-000001", "x:Impairment", True)
    atom, _, _, _ = decompose_concept("x:Impairment", lex, evidence=satisfied)
    assert atom.head == "H_EXPENSE"
    unsatisfied = EvidenceContext("0000000001-24-000001", "x:Impairment", False)
    atom, _, _, _ = decompose_concept("x:Impairment", lex, evidence=unsatisfied)
    assert atom.head == "H_UNKNOWN"


def test_impairment_descriptive_tag_spans_heads_without_moving_them() -> None:
    """The impairment tag filters across heads; heads and family EXACT hold."""
    from edgar_sec.engine.xbrl.solve.equivalence import EXACT, UNRELATED, classify_pair

    from edgar_sec.engine.xbrl.normalize.lexicon import EvidenceContext

    tax = load_domain_taxonomy()
    assert tax.token_lexicon is not None
    lex = tax.token_lexicon

    def attested(qname: str) -> EvidenceContext:
        return EvidenceContext("0000000001-24-000001", qname, True)

    loss_qname = "us-gaap:ImpairmentOfOilAndGasProperties"
    loss, _, _, _ = decompose_concept(loss_qname, lex, evidence=attested(loss_qname))
    held_qname = "us-gaap:ImpairmentOfLongLivedAssetsHeldForUse"
    held, _, _, _ = decompose_concept(held_qname, lex, evidence=attested(held_qname))
    disposed_qname = "us-gaap:ImpairmentOfLongLivedAssetsToBeDisposedOf"
    disposed, _, _, _ = decompose_concept(
        disposed_qname, lex, evidence=attested(disposed_qname)
    )
    population, _, _, _ = decompose_concept(
        "us-gaap:FinancingReceivableCollectivelyEvaluatedForImpairment", lex
    )
    balance, _, _, _ = decompose_concept(
        "asml:AccumulatedDepreciationDepletionAmortizationAndImpairment"
        "PropertyPlantAndEquipment",
        lex,
    )
    textblock, _, _, _ = decompose_concept(
        "nee:ImpairmentOfEquityMethodInvestmentsPolicyPolicyTextBlock", lex
    )
    for atom in (loss, held, disposed, population, balance, textblock):
        assert "M_IMPAIRMENT" in atom.modifiers
    assert loss.head == "H_INCOME"
    assert population.head == "H_ASSET"
    assert balance.head == "H_ASSET"
    assert textblock.head == "H_ASSET"
    assert classify_pair(held, disposed) == EXACT
    assert classify_pair(loss, population) == UNRELATED


def test_descriptive_tags_ride_across_heads_part2() -> None:
    """Accumulated/cumulative/litigation/environmental tags cross heads."""
    tax = load_domain_taxonomy()
    assert tax.token_lexicon is not None
    lex = tax.token_lexicon
    contra, _, _, _ = decompose_concept(
        "us-gaap:AccumulatedDepreciationDepletionAndAmortization", lex
    )
    aoci, _, _, _ = decompose_concept(
        "us-gaap:AccumulatedOtherComprehensiveIncomeLossNetOfTax", lex
    )
    hedge, _, _, _ = decompose_concept(
        "us-gaap:FairValueHedgeCumulativeIncreaseDecreaseInFairValueOfHedgedItem",
        lex,
    )
    settlement, _, _, _ = decompose_concept("us-gaap:LitigationSettlementExpense", lex)
    remediation, _, _, _ = decompose_concept(
        "us-gaap:EnvironmentalRemediationExpense", lex
    )
    assert "M_ACCUMULATED" in contra.modifiers and contra.head == "H_ASSET"
    assert "M_ACCUMULATED" in aoci.modifiers and aoci.head == "H_EQUITY"
    assert "M_CUMULATIVE" in hedge.modifiers
    assert settlement.head == "H_EXPENSE"
    assert settlement.modifiers == frozenset({"M_LITIGATION", "M_SETTLEMENT"})
    assert remediation.modifiers == frozenset({"M_ENVIRONMENTAL"})
    assert remediation.head == "H_EXPENSE"


def test_revenue_components_carry_identity_off_the_bare_atom() -> None:
    """Fee/commission components decompose distinctly from headline Revenues."""
    tax = load_domain_taxonomy()
    assert tax.token_lexicon is not None
    lex = tax.token_lexicon

    def atom_of(qname: str):
        atom, _, _, _ = decompose_concept(qname, lex)
        return atom

    headline = atom_of("us-gaap:Revenues")
    assert headline.head == "H_REVENUE"
    assert headline.modifiers == frozenset()

    expected = {
        "bac:FeesAndCommissions1": {"M_FEES_COMMISSIONS"},
        "jpm:FeesAndCommissions1": {"M_FEES_COMMISSIONS"},
        "jpm:FeesAndCommissionsDepositorAccounts1": {
            "M_FEES_COMMISSIONS",
            "M_DEPOSITOR_ACCOUNTS",
        },
        "jpm:FeesAndCommissionsLendingActivities": {
            "M_FEES_COMMISSIONS",
            "M_LENDING_ACTIVITIES",
        },
        "jpm:FeesAndCommissionsOther1": {"M_FEES_COMMISSIONS", "M_OTHER"},
        "jpm:MortgageProductionRevenue": {"M_MORTGAGE_PRODUCTION"},
        "us-gaap:BrokerageCommissionsRevenue": {"M_BROKERAGE_COMMISSIONS"},
        "us-gaap:PrincipalTransactionsRevenue": {"M_PRINCIPAL_TRANSACTIONS"},
        "pld:ManagementFeesRevenue1": {"M_MANAGEMENT_FEES"},
        "us-gaap:PropertyManagementFeeRevenue": {"M_MANAGEMENT_FEES"},
    }
    atoms = {}
    for qname, mods in expected.items():
        atom = atom_of(qname)
        assert atom.head == "H_REVENUE", qname
        assert atom.modifiers == frozenset(mods), qname
        assert atom != headline, qname
        atoms[qname] = atom

    # JPM's enumerated components are pairwise distinct atoms.
    jpm_atoms = [a for q, a in atoms.items() if q.startswith("jpm:")]
    jpm_atoms.append(atom_of("us-gaap:BrokerageCommissionsRevenue"))
    jpm_atoms.append(atom_of("us-gaap:PrincipalTransactionsRevenue"))
    assert len(set(jpm_atoms)) == len(jpm_atoms)

    # The fees stem carries onto already-identified component lines.
    servicing = atom_of("us-gaap:FeesAndCommissionsMortgageBankingAndServicing")
    assert servicing.modifiers == frozenset(
        {"M_FEES_COMMISSIONS", "M_MORTGAGE_BANKING"}
    )

    # The XVA name carries the valuation-adjustment coordinate.
    xva = atom_of("bac:DerivativeFundingRiskValuationAdjustmentDerivativeAssets")
    assert xva.head == "H_ASSET"
    assert xva.modifiers == frozenset({"M_DERIVATIVE", "M_VALUATION_ADJUSTMENT"})


def test_adjustment_coordinates_claim_only_their_terms() -> None:
    """Valuation/reclassification adjustments claim; other senses stay residual."""
    tax = load_domain_taxonomy()
    assert tax.token_lexicon is not None
    lex = tax.token_lexicon

    def atom_of(qname: str):
        atom, _, _, _ = decompose_concept(qname, lex)
        return atom

    cva_assets = atom_of(
        "us-gaap:DerivativeCreditRiskValuationAdjustmentDerivativeAssets"
    )
    assert cva_assets.head == "H_ASSET"
    assert cva_assets.modifiers == frozenset(
        {"M_DERIVATIVE", "M_RISK_CREDIT", "M_VALUATION_ADJUSTMENT"}
    )
    cva_liabs = atom_of(
        "us-gaap:DerivativeCreditRiskValuationAdjustmentDerivativeLiabilities"
    )
    assert cva_liabs.head == "H_LIABILITY"
    assert "M_VALUATION_ADJUSTMENT" in cva_liabs.modifiers

    singular = atom_of(
        "amzn:OtherComprehensiveIncomeLossReclassificationAdjustmentFromAOCINetOfTax"
    )
    assert singular.modifiers == frozenset({"M_OCI", "M_RECLASS_ADJUSTMENT", "V_NET"})
    plural = atom_of(
        "us-gaap:OtherComprehensiveIncomeLossAvailableForSaleSecurities"
        "AdjustmentBeforeReclassificationAdjustmentsAndTax"
    )
    assert "M_RECLASS_ADJUSTMENT" in plural.modifiers

    # The plural valuation phrase names other relations and never claims.
    for qname in (
        "us-gaap:FederalHomeLoanBankAdvancesValuationAdjustmentsForHedgingActivities",
        "us-gaap:OtherRealEstateValuationAdjustments",
    ):
        assert "M_VALUATION_ADJUSTMENT" not in atom_of(qname).modifiers


def _text_rule():
    from edgar_sec.engine.xbrl.taxonomy.item_types import text_coordinate_rule

    return text_coordinate_rule(load_domain_taxonomy())


def _declaration(qname: str, item_type: str) -> ConceptDeclaration:
    return ConceptDeclaration(
        concept_qname=qname, name=qname.partition(":")[2], item_type=item_type
    )


def test_text_coordinate_asserted_from_declared_string_type() -> None:
    """A string-typed narrative gains the coordinate its name never claims."""
    tax = load_domain_taxonomy()
    lex = tax.token_lexicon
    assert lex is not None
    qname = "us-gaap:RelatedPartyTransactionDescriptionOfTransaction"
    plain = decompose_concept_expression(qname, lex).atom
    assert "M_TEXT_NODE" not in plain.modifiers
    typed = decompose_concept_expression(
        qname, lex, _declaration(qname, "xbrli:stringItemType"), _text_rule()
    ).atom
    assert "M_TEXT_NODE" in typed.modifiers
    assert typed.head == plain.head
    assert typed.modifiers == plain.modifiers | {"M_TEXT_NODE"}


def test_text_coordinate_follows_type_not_name() -> None:
    """A TextBlock name with a numeric declared type gets no coordinate."""
    tax = load_domain_taxonomy()
    lex = tax.token_lexicon
    assert lex is not None
    qname = "us-gaap:SignificantAccountingPoliciesTextBlock"
    typed = decompose_concept_expression(
        qname, lex, _declaration(qname, "xbrli:monetaryItemType"), _text_rule()
    ).atom
    assert "M_TEXT_NODE" not in typed.modifiers
    block = decompose_concept_expression(
        qname, lex, _declaration(qname, "dtr-types:textBlockItemType"), _text_rule()
    ).atom
    assert "M_TEXT_NODE" in block.modifiers


def test_text_coordinate_absent_declaration_is_byte_identical() -> None:
    """No declaration (or no rule) reproduces today's atoms exactly."""
    tax = load_domain_taxonomy()
    lex = tax.token_lexicon
    assert lex is not None
    specimens = (
        "us-gaap:SignificantAccountingPoliciesTextBlock",
        "us-gaap:RelatedPartyTransactionDescriptionOfTransaction",
        "us-gaap:Revenues",
        "us-gaap:AccumulatedOtherComprehensiveIncomeLossNetOfTax",
    )
    for qname in specimens:
        baseline = decompose_concept_expression(qname, lex)
        assert decompose_concept_expression(qname, lex, None, _text_rule()) == baseline
        assert (
            decompose_concept_expression(
                qname, lex, _declaration(qname, "dtr-types:textBlockItemType"), None
            )
            == baseline
        )


def _percent_rule():
    from edgar_sec.engine.xbrl.taxonomy.item_types import percent_coordinate_rule

    return percent_coordinate_rule(load_domain_taxonomy())


def test_percent_coordinate_asserted_from_declared_percent_type() -> None:
    """A percent-typed extension gains the coordinate from its declared type."""
    tax = load_domain_taxonomy()
    lex = tax.token_lexicon
    assert lex is not None
    qname = "hon:RevenueFromContractWithCustomerPercentage"
    plain = decompose_concept_expression(qname, lex).atom
    assert "M_PERCENT_TYPED" not in plain.modifiers
    typed = decompose_concept_expression(
        qname,
        lex,
        _declaration(qname, "dtr-types1:percentItemType"),
        percent_rule=_percent_rule(),
    ).atom
    assert "M_PERCENT_TYPED" in typed.modifiers
    assert typed.head == plain.head
    assert typed.modifiers == plain.modifiers | {"M_PERCENT_TYPED"}


def test_percent_coordinate_follows_type_not_name() -> None:
    """A Percentage name with a monetary declared type gets no coordinate."""
    tax = load_domain_taxonomy()
    lex = tax.token_lexicon
    assert lex is not None
    qname = "hon:RevenueFromContractWithCustomerPercentage"
    typed = decompose_concept_expression(
        qname,
        lex,
        _declaration(qname, "xbrli:monetaryItemType"),
        percent_rule=_percent_rule(),
    ).atom
    assert "M_PERCENT_TYPED" not in typed.modifiers
    rate = "us-gaap:OperatingLeaseWeightedAverageDiscountRate"
    rated = decompose_concept_expression(
        rate,
        lex,
        _declaration(rate, "dtr-types:percentItemType"),
        percent_rule=_percent_rule(),
    ).atom
    assert "M_PERCENT_TYPED" in rated.modifiers


def test_percent_coordinate_absent_declaration_is_byte_identical() -> None:
    """No declaration (or no rule) reproduces today's atoms exactly."""
    tax = load_domain_taxonomy()
    lex = tax.token_lexicon
    assert lex is not None
    qname = "hon:RevenueFromContractWithCustomerPercentage"
    baseline = decompose_concept_expression(qname, lex)
    assert (
        decompose_concept_expression(qname, lex, None, percent_rule=_percent_rule())
        == baseline
    )
    assert (
        decompose_concept_expression(
            qname, lex, _declaration(qname, "dtr-types:percentItemType"), None
        )
        == baseline
    )


def test_text_coordinate_net_of_headline_only() -> None:
    """NET_OF: the headline atom gains the coordinate; operands stay name-derived."""
    tax = load_domain_taxonomy()
    lex = tax.token_lexicon
    assert lex is not None
    qname = "us-gaap:AccumulatedOtherComprehensiveIncomeLossNetOfTax"
    typed = decompose_concept_expression(
        qname, lex, _declaration(qname, "dtr-types:textBlockItemType"), _text_rule()
    )
    assert "M_TEXT_NODE" in typed.atom.modifiers
    assert all("M_TEXT_NODE" not in operand.modifiers for operand in typed.operands)


def test_step4_batch1_admitted_families_decompose_to_their_heads() -> None:
    """Step 4 batch 1: general H_UNKNOWN families gain their archive-evidenced heads."""
    tax = load_domain_taxonomy()
    assert tax.token_lexicon is not None
    lex = tax.token_lexicon
    expected = {
        "us-gaap:MortgageLoansOnRealEstate": ("H_ASSET", {"M_LOAN", "M_REAL_ESTATE"}),
        "us-gaap:MortgageLoansOnRealEstateCommercialAndConsumerNet": (
            "H_ASSET",
            {"V_NET"},
        ),
        "us-gaap:MortgageLoansOnRealEstateNewMortgageLoans": ("H_ASSET", {"M_LOAN"}),
        "us-gaap:SummaryOfInvestmentsOtherThanInvestmentsInRelatedPartiesCarryingAmount": (
            "H_ASSET",
            {"M_INVESTMENT", "M_CARRYING_AMOUNT"},
        ),
        "us-gaap:SummaryOfInvestmentsOtherThanInvestmentsInRelatedPartiesFairValue": (
            "H_ASSET",
            {"M_INVESTMENT", "M_FAIR_VALUE"},
        ),
        "us-gaap:RetainedInterestFairValueDisclosure": ("H_ASSET", {"M_FAIR_VALUE"}),
        "us-gaap:InterestsContinuedToBeHeldByTransferorFairValue": ("H_ASSET", set()),
        "us-gaap:InvestmentInPhysicalCommoditiesFairValueDisclosure": (
            "H_ASSET",
            {"M_INVESTMENT"},
        ),
        "us-gaap:MortgagesHeldForSaleFairValueDisclosure": (
            "H_ASSET",
            {"M_LOAN", "M_PURPOSE_SALE"},
        ),
        "us-gaap:PrincipalAmountOutstandingOnLoansManagedAndSecuritized": (
            "H_ASSET",
            {"M_LOAN"},
        ),
        "us-gaap:EscrowDeposit": ("H_ASSET", set()),
        "us-gaap:PrepaidRent": ("H_ASSET", {"M_PREPAID"}),
        "us-gaap:ContractWithCustomerRightToRecoverProductCurrent": (
            "H_ASSET",
            {"M_CURRENT"},
        ),
        "us-gaap:IndefiniteLivedTradeNames": (
            "H_ASSET",
            {"M_INDEFINITE_LIVED", "M_TRADEMARK"},
        ),
        "us-gaap:FinancialInstrumentsOwnedDerivativesAndOtherContractualAgreementsAtFairValue": (
            "H_ASSET",
            {"M_FINANCIAL_INSTRUMENT"},
        ),
        "us-gaap:SecuritiesForReverseRepurchaseAgreements": (
            "H_ASSET",
            {"M_COLLATERAL"},
        ),
        "us-gaap:JuniorSubordinatedNotes": (
            "H_LIABILITY",
            {"M_DEBT", "M_SUBORDINATED"},
        ),
        "us-gaap:LinesOfCreditCurrent": (
            "H_LIABILITY",
            {"M_DEBT_BORROWING", "M_CURRENT"},
        ),
        "us-gaap:BridgeLoan": ("H_LIABILITY", {"M_DEBT"}),
        "ifrs-full:CurrentSecuredBankLoansReceivedAndCurrentPortionOfNoncurrentSecuredBankLoansReceived": (
            "H_LIABILITY",
            {"M_DEBT"},
        ),
        "us-gaap:InterestBearingDomesticDepositBrokered": (
            "H_LIABILITY",
            {"M_DEPOSIT_LIABILITY"},
        ),
        "us-gaap:InterestBearingForeignDepositCertificatesOfDeposits": (
            "H_LIABILITY",
            {"M_DEPOSIT_LIABILITY"},
        ),
        "us-gaap:LongtermPollutionControlBondCurrentAndNoncurrent": (
            "H_LIABILITY",
            {"M_DEBT"},
        ),
        "us-gaap:PolicyholderFunds": ("H_LIABILITY", set()),
        "us-gaap:TierOneLeverageCapital": ("H_EQUITY", set()),
        "us-gaap:TierOneLeverageCapitalRequiredToBeWellCapitalized": (
            "H_EQUITY",
            set(),
        ),
        "srt:AlternativeExcessNetCapital": ("H_EQUITY", set()),
        "srt:AlternativeNetCapitalRequirement1": ("H_EQUITY", set()),
        "us-gaap:NoncontrollingInterestInVariableInterestEntity": (
            "H_EQUITY",
            {"M_NONCONTROLLING_INTEREST", "M_VARIABLE_INTEREST_ENTITY"},
        ),
        "us-gaap:NumberOfBusinessesAcquired": ("H_UNIT_RATE", set()),
        "us-gaap:NumberOfStores": ("H_UNIT_RATE", set()),
        "us-gaap:NumberOfAircraftOperated": ("H_UNIT_RATE", set()),
        "us-gaap:NumberOfStatesInWhichEntityOperates": ("H_UNIT_RATE", set()),
        "srt:SECScheduleIIIRealEstateNumberOfUnits": ("H_UNIT_RATE", {"M_REAL_ESTATE"}),
        "us-gaap:DerivativeSwaptionInterestRate": ("H_UNIT_RATE", {"M_RISK_IR"}),
        "us-gaap:DerivativeForwardExchangeRate1": ("H_UNIT_RATE", set()),
        "us-gaap:ForeignCurrencyExchangeRateRemeasurement1": (
            "H_UNIT_RATE",
            {"M_FX_CURRENCY", "M_RISK_FX"},
        ),
        "us-gaap:ForeignCurrencyExchangeRateTranslation1": (
            "H_UNIT_RATE",
            {"M_FX_CURRENCY", "M_RISK_FX"},
        ),
        "us-gaap:CombinedRatio": ("H_UNIT_RATE", set()),
        "dei:EntityListingDepositoryReceiptRatio": ("H_UNIT_RATE", set()),
        "us-gaap:RelatedPartyTransactionRate": ("H_UNIT_RATE", {"M_RELATED_PARTY"}),
        "us-gaap:WeightedAverageRateDomesticDepositCertificatesOfDeposit": (
            "H_UNIT_RATE",
            {"M_WEIGHTED_AVERAGE"},
        ),
        "us-gaap:PolicyholderAccountBalanceWeightedAverageCreditingRate": (
            "H_UNIT_RATE",
            {"M_WEIGHTED_AVERAGE"},
        ),
        "us-gaap:PolicyholderAccountBalanceAboveGuaranteedMinimumCreditingRate": (
            "H_UNIT_RATE",
            set(),
        ),
        "us-gaap:BankingRegulationCapitalConservationBufferCapitalConservedMinimum": (
            "H_UNIT_RATE",
            set(),
        ),
        "us-gaap:BankingRegulationCountercyclicalCapitalBuffer": ("H_UNIT_RATE", set()),
        "us-gaap:BankingRegulationGlobalSystemicallyImportantBankGsibSurcharge": (
            "H_UNIT_RATE",
            set(),
        ),
        "us-gaap:BankingRegulationLeverageBufferMinimum": ("H_UNIT_RATE", set()),
        "us-gaap:TranslationAdjustmentForNetInvestmentHedgeIncreaseDecreaseNetOfTax": (
            "H_INCOME",
            {"M_FX_CTA", "M_NET_INVESTMENT_HEDGE"},
        ),
        "us-gaap:TranslationAdjustmentFunctionalToReportingCurrencyNetOfTaxPeriodIncreaseDecrease": (
            "H_INCOME",
            {"M_FX_CTA"},
        ),
        "us-gaap:LitigationSettlementAmountAwardedFromOtherParty": (
            "H_INCOME",
            {"M_LITIGATION"},
        ),
        "us-gaap:CapitalExpenditureDiscontinuedOperations": ("H_CASH", {"M_PPE_CAPEX"}),
    }
    for qname, (head, mods) in expected.items():
        atom, _, _, _ = decompose_concept(qname, lex)
        assert atom.head == head, qname
        assert mods <= atom.modifiers, qname


def test_step4_batch1_scoped_phrases_do_not_steal_host_heads() -> None:
    """Batch 1 refusals: host-instrument, cash-flow, and ratio heads stay put."""
    tax = load_domain_taxonomy()
    assert tax.token_lexicon is not None
    lex = tax.token_lexicon
    hosts = {
        "us-gaap:ProceedsFromLinesOfCredit": "H_CASH",
        "us-gaap:DebtInstrumentBasisSpreadOnVariableRate": "H_LIABILITY",
        "us-gaap:RatioOfIndebtednessToNetCapital1": "H_UNIT_RATE",
        "us-gaap:PaymentsToAcquireFederalHomeLoanBankStock": "H_CASH",
        "us-gaap:CashAndSecuritiesSegregatedUnderFederalAndOtherRegulations": "H_CASH",
        "us-gaap:DefinedBenefitPlanAssumptionsUsedCalculatingBenefitObligationWeightedAverageInterestCreditingRate": "H_LIABILITY",
        "us-gaap:DerivativeAssetNumberOfInstrumentsHeld": "H_ASSET",
    }
    for qname, head in hosts.items():
        atom, _, _, _ = decompose_concept(qname, lex)
        assert atom.head == head, qname
    schw, _, _, _ = decompose_concept(
        "schw:MortgageLoansOnRealEstatePercentOfLoansWithInterestOnlyPayments", lex
    )
    assert schw.head == "H_ASSET"


def test_step4_batch2_basis_modifiers_separate_bottomline_variants() -> None:
    """Step 4 batch 2: pro-forma and statutory bases discriminate their atoms."""
    tax = load_domain_taxonomy()
    assert tax.token_lexicon is not None
    lex = tax.token_lexicon
    expected = {
        "us-gaap:BusinessAcquisitionsProFormaNetIncomeLoss": (
            "H_INCOME",
            {"M_NET_BOTTOMLINE", "M_BUSINESS_COMBINATION", "M_PRO_FORMA"},
        ),
        "us-gaap:BusinessAcquisitionsProFormaRevenue": (
            "H_REVENUE",
            {"M_BUSINESS_COMBINATION", "M_PRO_FORMA"},
        ),
        "us-gaap:BusinessAcquisitionProFormaEarningsPerShareDiluted": (
            "H_UNIT_RATE",
            {"V_DILUTED", "M_PRO_FORMA"},
        ),
        "us-gaap:StatutoryAccountingPracticesStatutoryNetIncomeAmount": (
            "H_INCOME",
            {"M_NET_BOTTOMLINE", "M_STATUTORY_BASIS"},
        ),
        "us-gaap:StatutoryAccountingPracticesStatutoryCapitalAndSurplusBalance": (
            "H_EQUITY",
            {"M_STATUTORY_BASIS"},
        ),
    }
    for qname, (head, mods) in expected.items():
        atom, _, _, _ = decompose_concept(qname, lex)
        assert atom.head == head, qname
        assert mods <= atom.modifiers, qname
    target, _, _, _ = decompose_concept("us-gaap:NetIncomeLoss", lex)
    for qname in expected:
        atom, _, _, _ = decompose_concept(qname, lex)
        assert atom != target, qname


def test_step4_batch2_scoped_phrases_do_not_overclaim() -> None:
    """Batch 2 refusals: bare statutory, redeemable, parent-alone stay unmarked."""
    tax = load_domain_taxonomy()
    assert tax.token_lexicon is not None
    lex = tax.token_lexicon
    tax_rate, _, _, _ = decompose_concept(
        "us-gaap:EffectiveIncomeTaxRateReconciliationAtFederalStatutoryIncomeTaxRate",
        lex,
    )
    assert "M_STATUTORY_BASIS" not in tax_rate.modifiers
    redeemable_debt, _, _, _ = decompose_concept("us-gaap:RedeemableLongTermDebt", lex)
    assert "M_TEMPORARY_MEZZANINE" not in redeemable_debt.modifiers
    redeemable_nci, _, _, _ = decompose_concept(
        "us-gaap:RedeemableNoncontrollingInterestEquityCarryingAmount", lex
    )
    assert redeemable_nci.modifiers == {
        "M_CARRYING_AMOUNT",
        "M_NONCONTROLLING_INTEREST",
    }
    not_redeemable, _, _, _ = decompose_concept(
        "blk:FairValueMeasuredRecurringBasisUsingNetAssetPerShareValueRedemptionFrequencyNotRedeemable",
        lex,
    )
    assert "M_TEMPORARY_MEZZANINE" not in not_redeemable.modifiers


def test_string_lookup_step2_rollforward_movement_modifiers() -> None:
    """Step 2: view-consumed residual tokens are now declared modifiers.

    The specimen concepts decompose with no intent-bearing residuals.
    """
    tax = load_domain_taxonomy()
    assert tax.token_lexicon is not None
    lex = tax.token_lexicon
    expected = {
        "us-gaap:FairValueMeasurementWithUnobservableInputsReconciliationRecurringBasisAssetTransfersIntoLevel3": (
            "H_ASSET",
            {"M_FAIR_VALUE", "M_RECONCILIATION", "M_TRANSFER_IN"},
        ),
        "us-gaap:FairValueMeasurementWithUnobservableInputsReconciliationLiabilityTransfersOutOfLevel3": (
            "H_LIABILITY",
            {"M_FAIR_VALUE", "M_RECONCILIATION", "M_TRANSFER_OUT"},
        ),
        "us-gaap:DefinedBenefitPlanPlanAmendments": (
            "H_LIABILITY",
            {"M_PENSION_DEFINED_BENEFIT", "M_PLAN_AMENDMENT"},
        ),
        "us-gaap:DefinedBenefitPlanContributionsByEmployer": (
            "H_LIABILITY",
            {"M_PENSION_DEFINED_BENEFIT", "M_EMPLOYER_CONTRIBUTION"},
        ),
        "us-gaap:DefinedBenefitPlanPlanAssetsContributionsByPlanParticipant": (
            "H_ASSET",
            {
                "M_PENSION_DEFINED_BENEFIT",
                "M_PLAN_ASSETS",
                "M_PARTICIPANT_CONTRIBUTION",
            },
        ),
        "us-gaap:DefinedBenefitPlanActualReturnOnPlanAssets": (
            "H_ASSET",
            {"M_PENSION_DEFINED_BENEFIT", "M_PLAN_ASSETS", "M_ACTUAL_RETURN"},
        ),
        "us-gaap:DefinedBenefitPlanActuarialGainLoss": (
            "H_INCOME",
            {"M_PENSION_DEFINED_BENEFIT", "M_ACTUARIAL"},
        ),
        "us-gaap:DefinedBenefitPlanBenefitsPaid": (
            "H_LIABILITY",
            {"M_PENSION_DEFINED_BENEFIT", "M_BENEFITS_PAID"},
        ),
        "us-gaap:DefinedBenefitPlanCurtailments": (
            "H_LIABILITY",
            {"M_PENSION_DEFINED_BENEFIT", "M_CURTAILMENT"},
        ),
        "us-gaap:DefinedBenefitPlanSpecialTerminationBenefits": (
            "H_LIABILITY",
            {"M_PENSION_DEFINED_BENEFIT", "M_TERMINATION_BENEFIT"},
        ),
        "us-gaap:TreasuryStockSharesAcquired": (
            "H_SHARE",
            {"M_TREASURY_REPURCHASE", "M_ACQUIRED"},
        ),
        "us-gaap:StockIssuedDuringPeriodValueTreasuryStockReissued": (
            "H_EQUITY",
            {"M_TREASURY_REPURCHASE", "M_REISSUED"},
        ),
        "us-gaap:StockRepurchasedAndRetiredDuringPeriodValue": (
            "H_EQUITY",
            {"M_TREASURY_REPURCHASE", "M_RETIRED"},
        ),
        "us-gaap:SharesPaidForTaxWithholdingForShareBasedCompensation": (
            "H_SHARE",
            {"M_SBC", "M_TAX", "M_WITHHOLDING"},
        ),
        "us-gaap:AociBeforeTaxAttributableToParent": (
            "H_EQUITY",
            {"M_OCI", "M_PRETAX", "M_TAX", "M_ATTRIBUTABLE_PARENT"},
        ),
    }
    for qname, (head, mods) in expected.items():
        atom, residuals, _, _ = decompose_concept(qname, lex)
        assert atom.head == head, qname
        assert mods <= atom.modifiers, qname
        intent, _total = residual_counts(residuals)
        assert intent == 0, (qname, residuals)


def test_string_lookup_step3_other_change_and_post_tax_phrases() -> None:
    """Step 3: other-change name shapes and the after-reclassification
    phrasing decompose to their declared modifiers.
    """
    tax = load_domain_taxonomy()
    assert tax.token_lexicon is not None
    lex = tax.token_lexicon
    atom, residuals, _, _ = decompose_concept(
        "f:DefinedBenefitPlanOtherIncreaseDecreasePlanAssets", lex
    )
    assert "M_OTHER_CHANGE" in atom.modifiers
    assert "M_PLAN_ASSETS" in atom.modifiers
    atom, residuals, _, _ = decompose_concept(
        "us-gaap:OtherComprehensiveIncomeLossCashFlowHedgeGainLoss"
        "AfterReclassificationAndTaxParent",
        lex,
    )
    assert "M_POST_TAX" in atom.modifiers
    assert "M_OCI" in atom.modifiers


def test_facade_view_specimens_decompose_to_gate_coordinates() -> None:
    """Facade Step 3: long names the views gate on decompose as pinned,
    with residuals pinned exactly as the vocabulary-gap record.
    """
    tax = load_domain_taxonomy()
    assert tax.token_lexicon is not None
    lex = tax.token_lexicon
    expected = {
        "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax": (
            "H_REVENUE",
            {"M_CONTRACT_CUSTOMER", "M_PRETAX", "M_TAX"},
            (),
        ),
        "us-gaap:ContractWithCustomerLiabilityRevenueRecognized": (
            "H_LIABILITY",
            {"M_CONTRACT_CUSTOMER"},
            ("Recognized",),
        ),
        "us-gaap:ContractWithCustomerLiability": (
            "H_LIABILITY",
            {"M_CONTRACT_CUSTOMER"},
            (),
        ),
        "us-gaap:DeferredTaxAssetsOperatingLossCarryforwards": (
            "H_INCOME",
            {"M_OPERATING", "M_TAX_INCOME"},
            ("Carryforwards",),
        ),
        "us-gaap:DiscontinuedOperationIncomeLossFromDiscontinued"
        "OperationBeforeIncomeTax": (
            "H_INCOME",
            {"M_DISCONTINUED", "M_PRETAX", "M_TAX"},
            ("From",),
        ),
        "us-gaap:FairValueMeasurementWithUnobservableInputsReconciliation"
        "RecurringBasisAssetValue": (
            "H_ASSET",
            {"M_FAIR_VALUE", "M_RECONCILIATION"},
            ("Measurement", "With", "Value"),
        ),
        "us-gaap:FairValueMeasurementWithUnobservableInputsReconciliation"
        "RecurringBasisAssetPurchases": (
            "H_ASSET",
            {"M_FAIR_VALUE", "M_PURCHASE", "M_RECONCILIATION"},
            ("Measurement", "With"),
        ),
    }
    for qname, (head, mods, residuals) in expected.items():
        atom, res, _, _ = decompose_concept(qname, lex)
        assert atom.head == head, qname
        assert mods <= atom.modifiers, qname
        assert res == residuals, qname


def test_purchase_frame_attaches_act_and_outflow_direction() -> None:
    """Purchase-led flow lines carry the purchase act at direction -1.0."""
    tax = load_domain_taxonomy()
    assert tax.token_lexicon is not None
    lex = tax.token_lexicon

    atom, residuals, direction, _ = decompose_concept(
        "ifrs-full:PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities",
        lex,
    )
    assert atom.head == "H_ASSET"
    assert atom.modifiers == {"M_INVESTING", "M_PPE_CAPEX", "M_PURCHASE"}
    assert direction == -1.0
    assert "Purchase" not in residuals

    atom, residuals, direction, _ = decompose_concept(
        "ifrs-full:PurchaseOfFinancialInstrumentsClassifiedAsInvestingActivities",
        lex,
    )
    assert atom.head == "H_UNKNOWN"
    assert atom.modifiers == {"M_FINANCIAL_INSTRUMENT", "M_INVESTING", "M_PURCHASE"}
    assert direction == -1.0
    assert "Purchase" not in residuals


def test_purchase_frame_plural_flow_forms_carry_the_act() -> None:
    """Plural-led flow lines take the frame direction alongside the act."""
    tax = load_domain_taxonomy()
    assert tax.token_lexicon is not None
    lex = tax.token_lexicon

    atom, _, direction, _ = decompose_concept(
        "td:PurchasesOfDebtSecuritiesAtAmortizedCost", lex
    )
    assert atom.head == "H_ASSET"
    assert atom.modifiers == {"M_DEBT", "M_PURCHASE"}
    assert direction == -1.0

    atom, _, direction, _ = decompose_concept(
        "ifrs-full:PurchasesOfNaturedependentElectricity", lex
    )
    assert "M_PURCHASE" in atom.modifiers
    assert direction == -1.0


def test_purchase_frame_guards_hold_stock_and_rollforward_shapes() -> None:
    """Stock, obligation, member, and rollforward shapes keep base atoms."""
    tax = load_domain_taxonomy()
    assert tax.token_lexicon is not None
    lex = tax.token_lexicon
    expected = {
        "us-gaap:PurchaseObligation": ("H_LIABILITY", set(), 1.0),
        "us-gaap:PurchaseCommitmentMember": ("H_COMMITMENT", set(), 1.0),
        "us-gaap:PurchaseObligationDueInSecondYear": (
            "H_LIABILITY",
            {"M_MATURITY"},
            1.0,
        ),
        "ifrs-full:PurchaseOfTreasuryShares": ("H_SHARE", {"M_RISK_IR"}, 1.0),
        "ifrs-full:PurchasesFairValueMeasurementAssets": (
            "H_ASSET",
            {"M_FAIR_VALUE", "M_PURCHASE"},
            1.0,
        ),
        "ifrs-full:PurchasesFairValueMeasurementLiabilities": (
            "H_LIABILITY",
            {"M_FAIR_VALUE", "M_PURCHASE"},
            1.0,
        ),
    }
    for qname, (head, mods, direction) in expected.items():
        atom, _, found_direction, _ = decompose_concept(qname, lex)
        assert atom.head == head, qname
        assert atom.modifiers == mods, qname
        assert found_direction == direction, qname


def test_purchase_frame_declaration_vetoes_instant_and_text() -> None:
    """An instant or text declaration refuses the act for stock shapes."""
    tax = load_domain_taxonomy()
    assert tax.token_lexicon is not None
    lex = tax.token_lexicon
    from edgar_sec.engine.xbrl.taxonomy.item_types import text_coordinate_rule

    instant = ConceptDeclaration(
        concept_qname="us-gaap:PurchaseOptionsLand",
        name="PurchaseOptionsLand",
        period_type="instant",
        item_type="xbrli:monetaryItemType",
    )
    atom, _, direction, _ = decompose_concept(
        "us-gaap:PurchaseOptionsLand", lex, instant
    )
    assert "M_PURCHASE" not in atom.modifiers
    assert direction == 1.0

    text = ConceptDeclaration(
        concept_qname="us-gaap:PurchaseTransactionPolicy",
        name="PurchaseTransactionPolicy",
        period_type="duration",
        item_type="dtr-types:textBlockItemType",
    )
    atom, _, direction, _ = decompose_concept(
        "us-gaap:PurchaseTransactionPolicy",
        lex,
        text,
        text_coordinate_rule(tax),
    )
    assert "M_PURCHASE" not in atom.modifiers
    assert direction == 1.0


def test_purchase_frame_constructed_extension_forms() -> None:
    """Synthetic extension names: flow forms take the act, guards refuse.

    Unattested in the corpus: categorization by construction.
    """
    tax = load_domain_taxonomy()
    assert tax.token_lexicon is not None
    lex = tax.token_lexicon

    atom, _, direction, _ = decompose_concept(
        "acme:PurchaseOfWindTurbinesClassifiedAsInvestingActivities", lex
    )
    assert "M_PURCHASE" in atom.modifiers
    assert "M_INVESTING" in atom.modifiers
    assert direction == -1.0

    atom, _, direction, _ = decompose_concept(
        "acme:PurchaseOfRawMaterialsForProduction", lex
    )
    assert "M_PURCHASE" in atom.modifiers
    assert direction == -1.0

    atom, _, direction, _ = decompose_concept(
        "acme:PurchasesOfCloudServiceCredits", lex
    )
    assert "M_PURCHASE" in atom.modifiers
    assert direction == -1.0

    atom, _, direction, _ = decompose_concept(
        "acme:PurchaseObligationDueInSixthYear", lex
    )
    assert atom.head == "H_LIABILITY"
    assert "M_PURCHASE" not in atom.modifiers
    assert direction == 1.0

    atom, _, direction, _ = decompose_concept("acme:PurchaseOfOwnShares", lex)
    assert atom.head == "H_SHARE"
    assert "M_PURCHASE" not in atom.modifiers
    assert direction == 1.0

    atom, _, direction, _ = decompose_concept("acme:PurchasesOfTreasuryShares", lex)
    assert atom.head == "H_SHARE"
    assert direction == 1.0

    atom, _, direction, _ = decompose_concept(
        "acme:PurchasesOfFairValueMeasurementAssets", lex
    )
    assert atom.head == "H_ASSET"
    assert direction == 1.0


def test_purchase_frame_leaves_payments_and_proceeds_untouched() -> None:
    """The payments and proceeds coordinates keep their own directions."""
    tax = load_domain_taxonomy()
    assert tax.token_lexicon is not None
    lex = tax.token_lexicon

    atom, _, direction, _ = decompose_concept(
        "us-gaap:PaymentsToAcquirePropertyPlantAndEquipment", lex
    )
    assert atom.head == "H_CASH"
    assert "M_PURCHASE" not in atom.modifiers
    assert direction == -1.0

    atom, _, direction, _ = decompose_concept(
        "us-gaap:ProceedsFromSaleOfPropertyPlantAndEquipment", lex
    )
    assert atom.head == "H_CASH"
    assert "M_PURCHASE" not in atom.modifiers
    assert direction == 1.0


def test_disposal_claims_assert_the_exit_identity() -> None:
    """Disposal and derecognition forms carry M_DISPOSAL in every dialect."""
    tax = load_domain_taxonomy()
    assert tax.token_lexicon is not None
    lex = tax.token_lexicon

    atom, res, _, _ = decompose_concept(
        "ifrs-full:ProceedsFromDisposalOfPropertyPlantAndEquipment", lex
    )
    assert atom.head == "H_CASH"
    assert atom.modifiers == {"M_DISPOSAL", "M_PPE_CAPEX"}
    assert "Disposal" not in res

    atom, _, _, _ = decompose_concept(
        "ifrs-full:ProceedsFromDisposalsOfPropertyPlantAndEquipment", lex
    )
    assert atom.modifiers == {"M_DISPOSAL", "M_PPE_CAPEX"}

    atom, _, _, _ = decompose_concept(
        "acme:ProceedsFromDerecognitionOfWindTurbines", lex
    )
    assert atom.head == "H_CASH"
    assert "M_DISPOSAL" in atom.modifiers

    atom, _, _, _ = decompose_concept("us-gaap:PropertyPlantAndEquipmentDisposals", lex)
    assert atom.modifiers == {"M_DISPOSAL", "M_DISPOSAL_GROUP", "M_PPE_CAPEX"}


def test_sale_act_separated_from_purpose_and_goods() -> None:
    """Sale-as-act carries M_SALE; purpose and goods senses keep their markers."""
    tax = load_domain_taxonomy()
    assert tax.token_lexicon is not None
    lex = tax.token_lexicon

    atom, _, _, _ = decompose_concept("acme:SaleOfWindTurbines", lex)
    assert "M_SALE" in atom.modifiers
    assert "M_PURPOSE_SALE" not in atom.modifiers

    atom, _, _, _ = decompose_concept("acme:AssetsHeldForSaleWindPortfolio", lex)
    assert "M_PURPOSE_SALE" in atom.modifiers
    assert "M_SALE" not in atom.modifiers

    atom, _, _, _ = decompose_concept(
        "us-gaap:ProceedsFromSaleOfPropertyPlantAndEquipment", lex
    )
    assert atom.modifiers == {"M_PPE_CAPEX", "M_SALE"}

    atom, _, _, _ = decompose_concept(
        "ifrs-full:ProceedsFromSalesOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities",
        lex,
    )
    assert "M_SALE" in atom.modifiers
    assert "M_SALES_GOODS" not in atom.modifiers

    atom, _, _, _ = decompose_concept("us-gaap:CostsApplicableToSales", lex)
    assert "M_SALES_GOODS" in atom.modifiers
    assert "M_SALE" not in atom.modifiers


def test_gain_family_carries_the_disposal_gain_identity() -> None:
    """Gain/loss on disposal, sale, or extinguishment carries M_DISPOSAL_GAIN."""
    tax = load_domain_taxonomy()
    assert tax.token_lexicon is not None
    lex = tax.token_lexicon

    atom, _, _, _ = decompose_concept("us-gaap:GainLossOnSaleOfBusiness", lex)
    assert atom.head == "H_INCOME"
    assert atom.modifiers == {"M_DISPOSAL_GAIN", "M_SALE"}

    atom, _, _, _ = decompose_concept(
        "ifrs-full:GainsLossesOnDisposalsOfPropertyPlantAndEquipment", lex
    )
    assert atom.modifiers == {"M_DISPOSAL", "M_DISPOSAL_GAIN", "M_PPE_CAPEX"}

    atom, _, _, _ = decompose_concept("us-gaap:GainsLossesOnExtinguishmentOfDebt", lex)
    assert atom.modifiers == {"M_DEBT", "M_DISPOSAL_GAIN"}

    atom, _, _, _ = decompose_concept("acme:GainLossOnDisposalOfWindTurbines", lex)
    assert atom.modifiers == {"M_DISPOSAL", "M_DISPOSAL_GAIN"}


def test_gain_family_from_postfix_and_arising_forms() -> None:
    """From, postfix, and arising-from gain forms carry the gain identity."""
    tax = load_domain_taxonomy()
    assert tax.token_lexicon is not None
    lex = tax.token_lexicon

    atom, _, _, _ = decompose_concept("acme:GainFromDisposalOfWindTurbines", lex)
    assert atom.head == "H_INCOME"
    assert atom.modifiers == {"M_DISPOSAL", "M_DISPOSAL_GAIN"}

    atom, _, _, _ = decompose_concept("acme:LossFromSaleOfWindTurbines", lex)
    assert atom.modifiers == {"M_DISPOSAL_GAIN", "M_SALE"}

    atom, _, _, _ = decompose_concept("acme:GainsFromExtinguishmentOfWindTurbines", lex)
    assert atom.modifiers == {"M_DISPOSAL_GAIN"}

    atom, _, _, _ = decompose_concept("acme:WindTurbinesDisposalGain", lex)
    assert atom.modifiers == {"M_DISPOSAL", "M_DISPOSAL_GAIN"}

    atom, _, _, _ = decompose_concept("acme:WindTurbinesDisposalLoss", lex)
    assert atom.modifiers == {"M_DISPOSAL", "M_DISPOSAL_GAIN"}

    atom, _, _, _ = decompose_concept("acme:GainArisingFromSaleOfWindTurbines", lex)
    assert atom.modifiers == {"M_DISPOSAL_GAIN", "M_SALE"}

    atom, _, _, _ = decompose_concept(
        "ifrs-full:GainsLossesArisingFromSaleAndLeasebackTransactions", lex
    )
    assert atom.modifiers == {"M_DISPOSAL_GAIN", "M_SALE"}

    atom, _, _, _ = decompose_concept(
        "us-gaap:CryptoAssetCumulativeRealizedGainFromDisposition", lex
    )
    assert "M_DISPOSAL_GAIN" in atom.modifiers


def test_gross_unrealized_positions_carry_side_markers() -> None:
    """Gross unrealized gain and loss positions carry distinct side markers."""
    tax = load_domain_taxonomy()
    assert tax.token_lexicon is not None
    lex = tax.token_lexicon

    atom, _, _, _ = decompose_concept(
        "us-gaap:AvailableForSaleDebtSecuritiesAccumulatedGrossUnrealizedGainBeforeTax",
        lex,
    )
    assert "V_GAIN_SIDE" in atom.modifiers
    assert "V_LOSS_SIDE" not in atom.modifiers

    atom, _, _, _ = decompose_concept(
        "us-gaap:AvailableForSaleDebtSecuritiesAccumulatedGrossUnrealizedLossBeforeTax",
        lex,
    )
    assert "V_LOSS_SIDE" in atom.modifiers
    assert "V_GAIN_SIDE" not in atom.modifiers

    atom, _, _, _ = decompose_concept(
        "us-gaap:DebtSecuritiesAvailableForSaleAccumulatedGrossUnrealizedGainLossBeforeTax",
        lex,
    )
    assert "V_GAIN_SIDE" not in atom.modifiers
    assert "V_LOSS_SIDE" not in atom.modifiers

    atom, _, _, _ = decompose_concept(
        "us-gaap:AvailableForSaleDebtSecuritiesGrossUnrealizedGain", lex
    )
    assert "V_GAIN_SIDE" in atom.modifiers

    atom, _, _, _ = decompose_concept(
        "us-gaap:AvailableForSaleDebtSecuritiesGrossUnrealizedLoss", lex
    )
    assert "V_LOSS_SIDE" in atom.modifiers


def test_financial_assets_object_claim() -> None:
    """Financial-asset phrases assert the instrument object on purchase lines."""
    tax = load_domain_taxonomy()
    assert tax.token_lexicon is not None
    lex = tax.token_lexicon

    atom, _, direction, _ = decompose_concept(
        "ifrs-full:PurchaseOfAvailableforsaleFinancialAssets", lex
    )
    assert atom.head == "H_ASSET"
    assert atom.modifiers == {
        "M_AVAILABLE_FOR_SALE",
        "M_FINANCIAL_INSTRUMENT",
        "M_PURCHASE",
    }
    assert direction == -1.0

    atom, _, _, _ = decompose_concept(
        "ifrs-full:PurchaseOfFinancialAssetsMeasuredAtAmortisedCostClassifiedAsInvestingActivities",
        lex,
    )
    assert "M_FINANCIAL_INSTRUMENT" in atom.modifiers
    assert "M_PURCHASE" in atom.modifiers


def test_wordform_issuance_and_settlement_nouns_carry_their_acts() -> None:
    """The singular nouns assert the carrier their plural forms assert."""
    tax = load_domain_taxonomy()
    assert tax.token_lexicon is not None
    lex = tax.token_lexicon

    singular, _, _, _ = decompose_concept("acme:IssuanceOfSolarBonds", lex)
    plural, _, _, _ = decompose_concept("acme:IssuancesOfSolarBonds", lex)
    assert singular == plural
    assert "M_ISSUANCE" in singular.modifiers

    atom, res, _, _ = decompose_concept(
        "us-gaap:ProceedsFromIssuanceOfLongTermDebt", lex
    )
    assert atom.modifiers == {"M_DEBT", "M_ISSUANCE", "M_NONCURRENT"}
    assert "Issuance" not in res

    singular, _, _, _ = decompose_concept("acme:SettlementOfInsuranceClaims", lex)
    plural, _, _, _ = decompose_concept("acme:SettlementsOfInsuranceClaims", lex)
    assert singular == plural
    assert "M_SETTLEMENT" in singular.modifiers

    atom, _, _, _ = decompose_concept(
        "us-gaap:DefinedBenefitPlanPlanAssetsLevel3ReconciliationDecreaseForSettlement",
        lex,
    )
    assert "M_SETTLEMENT" in atom.modifiers


def test_wordform_distribution_and_transfer_singulars_match_plurals() -> None:
    """Singular distribution and transfer forms land the plural atoms."""
    tax = load_domain_taxonomy()
    assert tax.token_lexicon is not None
    lex = tax.token_lexicon

    singular, _, _, _ = decompose_concept("acme:CashDistributionToMembers", lex)
    plural, _, _, _ = decompose_concept("acme:CashDistributionsToMembers", lex)
    assert singular == plural
    assert singular.modifiers == {"M_DIVIDEND"}

    singular, _, _, _ = decompose_concept("acme:TransferOfSolarAssets", lex)
    plural, _, _, _ = decompose_concept("acme:TransfersOfSolarAssets", lex)
    assert singular == plural
    assert singular.modifiers == {"M_TRANSFER"}

    singular, _, _, _ = decompose_concept("acme:TransferIntoLevel3SolarAssets", lex)
    plural, _, _, _ = decompose_concept("acme:TransfersIntoLevel3SolarAssets", lex)
    assert singular == plural
    assert "M_TRANSFER_IN" in singular.modifiers

    singular, _, _, _ = decompose_concept("acme:TransferOutOfLevel3SolarAssets", lex)
    plural, _, _, _ = decompose_concept("acme:TransfersOutOfLevel3SolarAssets", lex)
    assert singular == plural
    assert "M_TRANSFER_OUT" in singular.modifiers


def test_wordform_transfer_level_niche_accepts_to_and_from() -> None:
    """The benefit-plan dialect states Level-3 direction with To and From."""
    tax = load_domain_taxonomy()
    assert tax.token_lexicon is not None
    lex = tax.token_lexicon

    atom, _, _, _ = decompose_concept(
        "us-gaap-ebp:EmployeeBenefitPlanInvestmentLevel3ReconciliationIncreaseForTransferToLevel3",
        lex,
    )
    assert "M_TRANSFER_IN" in atom.modifiers
    atom, _, _, _ = decompose_concept(
        "us-gaap-ebp:EmployeeBenefitPlanInvestmentLevel3ReconciliationDecreaseForTransferFromLevel3",
        lex,
    )
    assert "M_TRANSFER_OUT" in atom.modifiers


def test_wordform_deferral_and_accrual_nouns_carry_the_stock_identity() -> None:
    """Deferral nouns assert M_DEFERRED; Accrual mirrors the Accruals claim."""
    tax = load_domain_taxonomy()
    assert tax.token_lexicon is not None
    lex = tax.token_lexicon

    singular, _, _, _ = decompose_concept("acme:DeferralOfSubscriptionRevenue", lex)
    plural, _, _, _ = decompose_concept("acme:DeferralsOfSubscriptionRevenue", lex)
    assert singular == plural
    assert "M_DEFERRED" in singular.modifiers

    atom, _, _, _ = decompose_concept(
        "ifrs-full:RegulatoryDeferralAccountBalances", lex
    )
    assert "M_DEFERRED" in atom.modifiers

    singular, _, _, _ = decompose_concept("acme:SolarWarrantyAccrual", lex)
    plural, _, _, _ = decompose_concept("acme:SolarWarrantyAccruals", lex)
    assert singular == plural
    assert singular.head == "H_LIABILITY"
    assert singular.modifiers == {"M_ACCRUED_LIABILITY"}

    atom, _, _, _ = decompose_concept(
        "us-gaap:LossContingencyAccrualAtCarryingValue", lex
    )
    assert "M_ACCRUED_LIABILITY" in atom.modifiers


def test_wordform_repayment_singular_holds_its_scoped_claim() -> None:
    """Repayment twins already agree; schedule attributes stay unclaimed."""
    tax = load_domain_taxonomy()
    assert tax.token_lexicon is not None
    lex = tax.token_lexicon

    singular, _, direction, _ = decompose_concept("acme:RepaymentOfSolarLoans", lex)
    plural, _, _, _ = decompose_concept("acme:RepaymentsOfSolarLoans", lex)
    assert singular == plural
    assert singular.head == "H_CASH"
    assert direction == -1.0

    atom, _, direction, _ = decompose_concept(
        "us-gaap:LongTermDebtMaturitiesRepaymentTerms", lex
    )
    assert atom.head == "H_LIABILITY"
    assert direction == 1.0


def test_wordform_borrowing_gerund_is_scoped_to_draw_shapes() -> None:
    """Borrowing under a facility mirrors Borrowings; cost topics refuse."""
    tax = load_domain_taxonomy()
    assert tax.token_lexicon is not None
    lex = tax.token_lexicon

    singular, _, _, _ = decompose_concept("acme:BorrowingUnderSolarFacility", lex)
    plural, _, _, _ = decompose_concept("acme:BorrowingsUnderSolarFacility", lex)
    assert singular == plural
    assert singular.head == "H_LIABILITY"
    assert "M_DEBT" in singular.modifiers

    atom, _, _, _ = decompose_concept("ifrs-full:BorrowingCostsCapitalised", lex)
    assert atom.head == "H_COST"
    assert "M_DEBT" not in atom.modifiers

    atom, res, _, _ = decompose_concept(
        "us-gaap:LineOfCreditFacilityMaximumBorrowingCapacity", lex
    )
    assert atom.modifiers == {"M_DEBT_BORROWING"}
    assert "Borrowing" in res


def test_wordform_impaired_participial_carries_the_tag() -> None:
    """Impaired asserts the same descriptive tag as the Impairment noun."""
    tax = load_domain_taxonomy()
    assert tax.token_lexicon is not None
    lex = tax.token_lexicon

    participial, _, _, _ = decompose_concept("acme:SolarLoansImpaired", lex)
    noun, _, _, _ = decompose_concept("acme:SolarLoanImpairment", lex)
    assert participial == noun
    assert "M_IMPAIRMENT" in participial.modifiers

    atom, res, _, _ = decompose_concept(
        "us-gaap:ImpairedFinancingReceivableRecordedInvestment", lex
    )
    assert "M_IMPAIRMENT" in atom.modifiers
    assert "Impaired" not in res


def test_wordform_amortisation_spelling_matches_us_spelling() -> None:
    """Amortisation twins land the Amortization atoms, heads included."""
    tax = load_domain_taxonomy()
    assert tax.token_lexicon is not None
    lex = tax.token_lexicon

    british, _, _, _ = decompose_concept("acme:AmortisationOfIntangibleAssets", lex)
    american, _, _, _ = decompose_concept("us-gaap:AmortizationOfIntangibleAssets", lex)
    assert british == american
    assert british.head == "H_EXPENSE"

    atom, res, _, _ = decompose_concept("ifrs-full:AmortisationExpense", lex)
    assert atom.modifiers == {"M_DEPR_AMORT"}
    assert res == ()

    british, _, _, _ = decompose_concept("acme:DepreciationAndAmortisationExpense", lex)
    american, _, _, _ = decompose_concept(
        "acme:DepreciationAndAmortizationExpense", lex
    )
    assert british == american


def test_wordform_availableforsale_fused_token_carries_the_classification() -> None:
    """The fused IFRS spelling asserts M_AVAILABLE_FOR_SALE like the phrase."""
    tax = load_domain_taxonomy()
    assert tax.token_lexicon is not None
    lex = tax.token_lexicon

    fused, _, _, _ = decompose_concept("acme:AvailableforsaleSolarBonds", lex)
    spelled, _, _, _ = decompose_concept("acme:AvailableForSaleSolarBonds", lex)
    assert fused == spelled
    assert "M_AVAILABLE_FOR_SALE" in fused.modifiers

    atom, _, direction, _ = decompose_concept(
        "us-gaap:PaymentsForProceedsFromAvailableforsaleSecuritiesShortterm", lex
    )
    assert "M_AVAILABLE_FOR_SALE" in atom.modifiers
    assert direction == -1.0

    fused, _, _, _ = decompose_concept(
        "acme:OtherComprehensiveIncomeNetOfTaxAvailableforsaleFinancialAssets", lex
    )
    spelled, _, _, _ = decompose_concept(
        "acme:OtherComprehensiveIncomeNetOfTaxAvailableForSaleFinancialAssets", lex
    )
    assert fused == spelled


def test_absent_acts_carry_dedicated_markers() -> None:
    """Each formerly absent act asserts its carrier on attested names."""
    tax = load_domain_taxonomy()
    assert tax.token_lexicon is not None
    lex = tax.token_lexicon

    specimens = {
        "us-gaap:ProceedsFromLoanOriginations1": "M_ORIGINATION",
        "ifrs-full:WritedownsReversalsOfInventories": "M_WRITE_OFF",
        "us-gaap:ProceedsFromCollectionOfFinanceReceivables": "M_COLLECTION",
        "ifrs-full:ReversalOfImpairmentLossRecognisedInProfitOrLossTradeReceivables": "M_REVERSAL",
        "ifrs-full:GainLossOnRemeasurementOfNetDefinedBenefitLiabilityAsset": "M_REMEASUREMENT",
        "us-gaap:PartnersCapitalAccountRedemptions": "M_REDEMPTION",
        "us-gaap:DebtInstrumentDecreaseForgiveness": "M_FORGIVENESS",
        "us-gaap:RecognitionOfDeferredRevenue": "M_RECOGNITION",
        "us-gaap:AccretionExpense": "M_ACCRETION",
        "ifrs-full:FinancialAssetsAtAmortisedCost": "M_AMORTISED_COST",
    }
    for qname, marker in specimens.items():
        atom, _, _, _ = decompose_concept(qname, lex)
        assert marker in atom.modifiers, qname

    atom, _, _, _ = decompose_concept("ifrs-full:WritedownsReversalsOfInventories", lex)
    assert atom.modifiers == {"M_REVERSAL", "M_WRITE_OFF"}

    atom, _, _, _ = decompose_concept(
        "us-gaap:ProceedsFromSaleAndCollectionOfFinanceReceivables", lex
    )
    assert atom.modifiers == {"M_COLLECTION", "M_FINANCING_RECEIVABLE", "M_SALE"}


def test_absent_act_attribute_guards_stay_byte_identical() -> None:
    """Attribute senses of the new acts' words keep their base atoms."""
    tax = load_domain_taxonomy()
    assert tax.token_lexicon is not None
    lex = tax.token_lexicon

    guards = {
        "us-gaap:DebtInstrumentRedemptionPricePercentageOfPrincipalAmountRedeemed": (
            "H_LIABILITY",
            {"M_DEBT", "M_FINANCIAL_INSTRUMENT", "M_PERCENT"},
        ),
        "ifrs-full:ActuarialAssumptionOfDiscountRates": ("H_UNIT_RATE", set()),
        "us-gaap:CollectionsIncludingWorkOfArtAndHistoricalTreasureMember": (
            "H_UNKNOWN",
            set(),
        ),
        "us-gaap:LeaseExpirationDate1": ("H_UNKNOWN", {"M_LEASE"}),
    }
    for qname, (head, modifiers) in guards.items():
        atom, _, _, _ = decompose_concept(qname, lex)
        assert atom.head == head, qname
        assert atom.modifiers == modifiers, qname


def test_payments_for_origination_keeps_outflow_direction() -> None:
    """The payments-for-origination anchor asserts the act, direction held."""
    tax = load_domain_taxonomy()
    assert tax.token_lexicon is not None
    lex = tax.token_lexicon

    for qname in (
        "us-gaap:PaymentsForOriginationAndPurchasesOfLoansHeldForSale",
        "us-gaap:PaymentsForOriginationOfMortgageLoansHeldForSale",
    ):
        atom, _, direction, _ = decompose_concept(qname, lex)
        assert "M_ORIGINATION" in atom.modifiers
        assert atom.head == "H_CASH"
        assert direction == -1.0


def test_declaration_keeps_dividend_identity_and_rate_head() -> None:
    """Per-share declared lines gain the act; dividend and head stand."""
    tax = load_domain_taxonomy()
    assert tax.token_lexicon is not None
    lex = tax.token_lexicon

    atom, _, _, _ = decompose_concept(
        "us-gaap:CommonStockDividendsPerShareDeclared", lex
    )
    assert atom.head == "H_UNIT_RATE"
    assert atom.modifiers == {"M_COMMON", "M_DECLARATION", "M_DIVIDEND"}


def test_step5_wordform_twins_land_the_same_atom() -> None:
    """Dialect and synonym twins of the new acts land identical atoms."""
    tax = load_domain_taxonomy()
    assert tax.token_lexicon is not None
    lex = tax.token_lexicon

    writeoff, _, _, _ = decompose_concept("acme:WriteoffOfSolarReceivables", lex)
    writedown, _, _, _ = decompose_concept("acme:WritedownOfSolarReceivables", lex)
    assert writeoff == writedown
    assert "M_WRITE_OFF" in writeoff.modifiers

    revaluation, _, _, _ = decompose_concept("acme:RevaluationOfSolarAssets", lex)
    remeasurement, _, _, _ = decompose_concept("acme:RemeasurementOfSolarAssets", lex)
    assert revaluation == remeasurement
    assert "M_REMEASUREMENT" in revaluation.modifiers

    fused, _, _, _ = decompose_concept(
        "acme:OtherThanTemporaryImpairmentLossesHeldtomaturitySecurities", lex
    )
    assert "M_HELD_TO_MATURITY" in fused.modifiers


def test_proceeds_frame_guarantees_the_cash_head() -> None:
    """Proceeds-led names land H_CASH; only the head moves."""
    tax = load_domain_taxonomy()
    assert tax.token_lexicon is not None
    lex = tax.token_lexicon

    atom, _, direction, _ = decompose_concept(
        "ifrs-full:ProceedsFromNoncurrentBorrowings", lex
    )
    assert atom.head == "H_CASH"
    assert atom.modifiers == {"M_DEBT", "M_NONCURRENT"}
    assert direction == 1.0

    atom, _, direction, _ = decompose_concept(
        "ifrs-full:ProceedsFromDisposalOfExplorationAndEvaluationAssets", lex
    )
    assert atom.head == "H_CASH"
    assert atom.modifiers == {"M_DISPOSAL"}
    assert direction == 1.0

    atom, _, _, _ = decompose_concept("us-gaap:ProceedsFromBankDebt", lex)
    assert atom.head == "H_CASH"
    assert atom.modifiers == {"M_DEBT"}

    atom, _, direction, _ = decompose_concept(
        "acme:ProceedsFromBorrowingsUnderSolarFacility", lex
    )
    assert atom.head == "H_CASH"
    assert atom.modifiers == {"M_DEBT"}
    assert direction == 1.0


def test_receipts_frame_guarantees_the_cash_head() -> None:
    """Receipts-led names land H_CASH; only the head moves."""
    tax = load_domain_taxonomy()
    assert tax.token_lexicon is not None
    lex = tax.token_lexicon

    atom, _, direction, _ = decompose_concept(
        "ifrs-full:ReceiptsFromRoyaltiesFeesCommissionsAndOtherRevenue", lex
    )
    assert atom.head == "H_CASH"
    assert atom.modifiers == {"M_OTHER"}
    assert direction == 1.0

    atom, _, direction, _ = decompose_concept("acme:ReceiptsRoyaltiesAndFees", lex)
    assert atom.head == "H_CASH"
    assert atom.modifiers == set()
    assert direction == 1.0


def test_proceeds_head_guarantee_leaves_other_names_untouched() -> None:
    """No proceeds prefix, no frame: stocks and NET_OF names stand."""
    tax = load_domain_taxonomy()
    assert tax.token_lexicon is not None
    lex = tax.token_lexicon

    atom, _, _, _ = decompose_concept("acme:BorrowingsUnderSolarFinancingFacility", lex)
    assert atom.head == "H_LIABILITY"

    atom, _, direction, _ = decompose_concept(
        "us-gaap:ProceedsFromDivestitureOfBusinessesNetOfCashDivested", lex
    )
    assert atom.head == "H_CASH"
    assert direction == 1.0


def test_proceeds_debt_phrases_claim_their_direction() -> None:
    """The specific-debt proceeds names bear direction; none is a default."""
    tax = load_domain_taxonomy()
    assert tax.token_lexicon is not None
    lex = tax.token_lexicon

    names = (
        "us-gaap:ProceedsFromConvertibleDebt",
        "us-gaap:ProceedsFromDebtMaturingInMoreThanThreeMonths",
        "us-gaap:ProceedsFromDebtNetOfIssuanceCosts",
        "us-gaap:ProceedsFromOtherShortTermDebt",
        "us-gaap:ProceedsFromRelatedPartyDebt",
        "us-gaap:ProceedsFromShortTermDebt",
        "us-gaap:ProceedsFromShortTermDebtAbstract",
        "us-gaap:ProceedsFromShortTermDebtMaturingInMoreThanThreeMonths",
        "us-gaap:ProceedsFromShortTermDebtMaturingInThreeMonthsOrLess",
    )
    for name in names:
        expr = decompose_concept_expression(name, lex)
        assert expr.direction == 1.0
        assert any(m.entry.direction is not None for m in expr.matches), name


def test_proceeds_census_claims_carry_the_source_acts() -> None:
    """Issue-form and annuities proceeds carry M_ISSUANCE; guards unchanged."""
    tax = load_domain_taxonomy()
    assert tax.token_lexicon is not None
    lex = tax.token_lexicon

    atom, _, _, _ = decompose_concept(
        "ifrs-full:ProceedsFromIssueOfOrdinaryShares", lex
    )
    assert atom.modifiers == {"M_ISSUANCE"}

    atom, _, _, _ = decompose_concept(
        "ifrs-full:ProceedsFromIssueOfBondsNotesAndDebentures", lex
    )
    assert atom.modifiers == {"M_DEBT", "M_ISSUANCE", "M_NONCURRENT"}

    atom, _, _, _ = decompose_concept("ifrs-full:ProceedsFromIssuingShares", lex)
    assert atom.head == "H_CASH"
    assert atom.modifiers == {"M_ISSUANCE"}

    atom, _, direction, _ = decompose_concept(
        "us-gaap:ProceedsFromAnnuitiesAndInvestmentCertificates", lex
    )
    assert atom.modifiers == {"M_INVESTMENT", "M_ISSUANCE"}
    assert direction == 1.0

    atom, _, direction, _ = decompose_concept(
        "us-gaap:RepaymentsOfAnnuitiesAndInvestmentCertificates", lex
    )
    assert atom.modifiers == {"M_INVESTMENT", "M_ISSUANCE"}
    assert direction == -1.0

    atom, _, _, _ = decompose_concept(
        "ifrs-full:DateOfAuthorisationForIssueOfFinancialStatements2013", lex
    )
    assert "M_ISSUANCE" not in atom.modifiers


def test_trailing_sale_proceeds_carry_the_sale_act() -> None:
    """The trailing Sale Proceeds form asserts M_SALE on the cash head."""
    tax = load_domain_taxonomy()
    assert tax.token_lexicon is not None
    lex = tax.token_lexicon

    atom, _, direction, _ = decompose_concept(
        "us-gaap:InvestmentSoldNotYetPurchasedSaleProceeds", lex
    )
    assert atom.head == "H_CASH"
    assert atom.modifiers == {"M_INVESTMENT", "M_SALE"}
    assert direction == 1.0

    atom, _, _, _ = decompose_concept("acme:SolarGenerationEquipmentSaleProceeds", lex)
    assert atom.head == "H_CASH"
    assert atom.modifiers == {"M_SALE"}


def test_notes_debt_class_admission_and_guards() -> None:
    """Notes decomposes as a debt-class head; receivable/disclosure stay put."""
    tax = load_domain_taxonomy()
    assert tax.token_lexicon is not None
    lex = tax.token_lexicon

    atom, residuals, _, _ = decompose_concept("us-gaap:NotePayable", lex)
    assert atom.head == "H_LIABILITY"
    assert atom.modifiers == {"M_DEBT"}
    assert residuals == ()

    atom, residuals, _, _ = decompose_concept(
        "us-gaap:AccountsAndNotesReceivableNet", lex
    )
    assert atom.head == "H_ASSET"
    assert atom.modifiers == {"M_RECEIVABLE", "V_NET"}
    assert residuals == ("Accounts",)

    atom, residuals, _, _ = decompose_concept("us-gaap:NotesToFinancialStatements", lex)
    assert atom.head == "H_UNKNOWN"
    assert atom.modifiers == frozenset()
    assert residuals == ("Notes", "To", "Financial", "Statements")

    leak = decompose_concept_expression("acme:NotePayableAndNotesReceivable", lex)
    assert leak.atom.head == "H_ASSET"
    assert leak.atom.modifiers == {"M_RECEIVABLE"}
    assert leak.operands[1].head == "H_LIABILITY"
    assert leak.operands[1].modifiers == {"M_DEBT"}


def test_rp_partner_compound_admissions() -> None:
    """R/P partner compounds decompose with their class identity asserted."""
    tax = load_domain_taxonomy()
    assert tax.token_lexicon is not None
    lex = tax.token_lexicon

    atom, residuals, _, _ = decompose_concept("ifrs-full:TradeReceivables", lex)
    assert atom.head == "H_ASSET"
    assert atom.modifiers == {"M_RECEIVABLE"}
    assert residuals == ()

    atom, residuals, _, _ = decompose_concept("ITMSF:TradePayables", lex)
    assert atom.head == "H_LIABILITY"
    assert atom.modifiers == {"M_ACCOUNTS_PAYABLE"}
    assert residuals == ()

    atom, residuals, _, _ = decompose_concept("cat:FinanceReceivablesNet", lex)
    assert atom.head == "H_ASSET"
    assert atom.modifiers == {"M_FINANCING_RECEIVABLE", "V_NET"}
    assert residuals == ()

    atom, residuals, _, _ = decompose_concept("us-gaap:OtherReceivables", lex)
    assert atom.head == "H_ASSET"
    assert atom.modifiers == {"M_OTHER"}
    assert residuals == ()

    atom, residuals, _, _ = decompose_concept("us-gaap:OtherIncome", lex)
    assert atom.head == "H_INCOME"
    assert atom.modifiers == {"M_OTHER"}
    assert residuals == ()

    atom, residuals, _, _ = decompose_concept("ifrs-full:TradeAndOtherReceivables", lex)
    assert atom.head == "H_ASSET"
    assert atom.modifiers == {"M_OTHER"}
    assert residuals == ("Trade",)

    atom, residuals, _, _ = decompose_concept("us-gaap:ManagementFeePayable", lex)
    assert atom.head == "H_LIABILITY"
    assert atom.modifiers == frozenset()
    assert residuals == ("Management",)

    atom, residuals, _, _ = decompose_concept(
        "hmr:BusinessAcquisitionInstallmentsPayable", lex
    )
    assert atom.head == "H_LIABILITY"
    assert atom.modifiers == {"M_BUSINESS_COMBINATION"}
    assert residuals == ()

    atom, residuals, _, _ = decompose_concept("ipa:AmountsReceivableNet", lex)
    assert atom.head == "H_ASSET"
    assert atom.modifiers == {"M_RECEIVABLE", "V_NET"}
    assert residuals == ()

    atom, residuals, _, _ = decompose_concept("ry:NotionalAmounts", lex)
    assert atom.head == "H_COMMITMENT"
    assert atom.modifiers == {"M_NOTIONAL_AMOUNT"}
    assert residuals == ()

    atom, residuals, _, _ = decompose_concept("chnr:TotalOthersPayables", lex)
    assert atom.head == "H_LIABILITY"
    assert atom.modifiers == frozenset()
    assert residuals == ("Total", "Others")
