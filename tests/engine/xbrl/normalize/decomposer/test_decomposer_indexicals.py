"""Decomposer tests: number and ordinal indexicals, phrase merges."""

from edgar_sec.engine.xbrl.normalize.decomposer import (
    decompose_concept,
    decompose_concept_expression,
    infer_semantic_frame,
)
from edgar_sec.engine.xbrl.taxonomy.domain import DomainTaxonomy


def test_infer_semantic_frame_canonical_and_unseen(tax: DomainTaxonomy) -> None:
    """Verify semantic frame extraction for canonical and unseen tags."""

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


def test_number_words_become_indexicals_not_residuals(tax: DomainTaxonomy) -> None:
    """Maturity siblings share one atom and differ only in num indexical."""
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


def test_number_range_merges_into_one_indexical(tax: DomainTaxonomy) -> None:
    """After Five Through Ten Years yields a single num=5..10 indexical."""
    assert tax.token_lexicon is not None

    _, _, _, indexicals = decompose_concept(
        "us-gaap:AvailableForSaleSecuritiesDebtMaturitiesAfterFiveThroughTenYearsAmortizedCost",
        tax.token_lexicon,
    )
    assert indexicals == ("num=5..10",)


def test_net_of_keeps_left_side_number_indexical(tax: DomainTaxonomy) -> None:
    """A number left of a NET_OF operator survives in the indexicals."""
    assert tax.token_lexicon is not None

    expression = decompose_concept_expression(
        "us-gaap:RevenueFromFiveYearContractNetOfInterestExpense", tax.token_lexicon
    )
    assert expression.operator == "NET_OF"
    assert expression.indexicals == ("num=5",)


def test_ordinals_share_atom_and_differ_as_indexicals(tax: DomainTaxonomy) -> None:
    """Ordinal maturity siblings: same atom, ord= indexicals carry the slot."""
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


def test_counterparty_and_past_due_phrase_merges(tax: DomainTaxonomy) -> None:
    """Third/Related Party and Past Due decompose as single modifiers."""
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


def test_mined_phrase_merges(tax: DomainTaxonomy) -> None:
    """Disposal group, off-balance-sheet, AFS/HTM phrases claim as units."""
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


def test_fiscal_year_is_an_indexical_not_a_modifier(tax: DomainTaxonomy) -> None:
    """Fiscal Year scopes a concept (indexical) instead of qualifying it."""
    assert tax.token_lexicon is not None
    expr = decompose_concept_expression(
        "cat:DefinedBenefitPlanHealthCareCostTrendRateAssumedForCurrentFiscalYear",
        tax.token_lexicon,
    )
    assert "FISCAL_YEAR" in expr.indexicals
    assert "M_MATURITY" not in expr.atom.modifiers


def test_fair_value_level_rides_the_number_grammar(tax: DomainTaxonomy) -> None:
    """Level 3 decomposes as M_FAIR_VALUE with the level as num= indexical."""
    assert tax.token_lexicon is not None
    expr = decompose_concept_expression(
        "us-gaap:DefinedBenefitPlanPlanAssetsLevel3ReconciliationDecreaseForSale",
        tax.token_lexicon,
    )
    assert "M_FAIR_VALUE" in expr.atom.modifiers
    assert "M_PENSION_DEFINED_BENEFIT" in expr.atom.modifiers
    assert expr.indexicals == ("num=3",)


def test_fused_longterm_spelling_keeps_the_stated_override(tax: DomainTaxonomy) -> None:
    """The fused Longterm spelling states the same override as Long Term."""
    assert tax.token_lexicon is not None
    fused, _, _, _ = decompose_concept(
        "us-gaap:AccountsPayableLongterm", tax.token_lexicon
    )
    spelled, _, _, _ = decompose_concept(
        "us-gaap:AccountsPayableLongTerm", tax.token_lexicon
    )
    assert fused == spelled
    assert fused.modifiers == frozenset({"M_ACCOUNTS_PAYABLE", "M_NONCURRENT"})


def test_anticipated_liabilities_infix_variants_share_attested_atoms(
    tax: DomainTaxonomy,
) -> None:
    """Unattested Liabilities-infix payable names land on attested atoms."""
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


def test_leading_long_term_on_payable_liabilities_is_tenor_not_horizon(
    tax: DomainTaxonomy,
) -> None:
    """A leading Long Term is tenor (D8/B2): it states no horizon bucket."""
    assert tax.token_lexicon is not None
    atom, res, _, _ = decompose_concept(
        "us-gaap:LongTermAccountsPayableLiabilities", tax.token_lexicon
    )
    assert res == ()
    assert "M_MATURITY" in atom.modifiers
    assert "M_NONCURRENT" not in atom.modifiers
    assert "M_CURRENT" not in atom.modifiers
