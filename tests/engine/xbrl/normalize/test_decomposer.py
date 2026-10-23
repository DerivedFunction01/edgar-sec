"""Unit tests for compositional concept decomposer and sub-atomic parsing."""

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
    assert composed.atom.modifiers == frozenset({"M_CURRENT", "M_MATURITY"})
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
    assert settlement.modifiers == frozenset({"M_LITIGATION"})
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
