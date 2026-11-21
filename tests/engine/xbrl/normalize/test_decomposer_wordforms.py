"""Decomposer tests: wordform twins across number and spelling."""

from edgar_sec.engine.xbrl.normalize.decomposer import decompose_concept
from edgar_sec.engine.xbrl.taxonomy.domain import DomainTaxonomy


def test_wordform_issuance_and_settlement_nouns_carry_their_acts(
    tax: DomainTaxonomy,
) -> None:
    """The singular nouns assert the carrier their plural forms assert."""
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


def test_wordform_distribution_and_transfer_singulars_match_plurals(
    tax: DomainTaxonomy,
) -> None:
    """Singular distribution and transfer forms land the plural atoms."""
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


def test_wordform_transfer_level_niche_accepts_to_and_from(tax: DomainTaxonomy) -> None:
    """The benefit-plan dialect states Level-3 direction with To and From."""
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


def test_wordform_deferral_and_accrual_nouns_carry_the_stock_identity(
    tax: DomainTaxonomy,
) -> None:
    """Deferral nouns assert M_DEFERRED; Accrual mirrors the Accruals claim."""
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


def test_wordform_repayment_singular_holds_its_scoped_claim(
    tax: DomainTaxonomy,
) -> None:
    """Repayment twins already agree; schedule attributes stay unclaimed."""
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


def test_wordform_borrowing_gerund_is_scoped_to_draw_shapes(
    tax: DomainTaxonomy,
) -> None:
    """Borrowing under a facility mirrors Borrowings; cost topics refuse."""
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


def test_wordform_impaired_participial_carries_the_tag(tax: DomainTaxonomy) -> None:
    """Impaired asserts the same descriptive tag as the Impairment noun."""
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


def test_wordform_amortisation_spelling_matches_us_spelling(
    tax: DomainTaxonomy,
) -> None:
    """Amortisation twins land the Amortization atoms, heads included."""
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


def test_wordform_availableforsale_fused_token_carries_the_classification(
    tax: DomainTaxonomy,
) -> None:
    """The fused IFRS spelling asserts M_AVAILABLE_FOR_SALE like the phrase."""
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
