"""Decomposer tests: admitted families, lookups, facade specimens."""

from edgar_sec.engine.xbrl.normalize.decomposer import (
    decompose_concept,
    residual_counts,
)
from edgar_sec.engine.xbrl.taxonomy.domain import DomainTaxonomy


def test_step4_batch1_admitted_families_decompose_to_their_heads(
    tax: DomainTaxonomy,
) -> None:
    """Step 4 batch 1: general H_UNKNOWN families gain their archive-evidenced heads."""
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


def test_step4_batch1_scoped_phrases_do_not_steal_host_heads(
    tax: DomainTaxonomy,
) -> None:
    """Batch 1 refusals: host-instrument, cash-flow, and ratio heads stay put."""
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


def test_step4_batch2_basis_modifiers_separate_bottomline_variants(
    tax: DomainTaxonomy,
) -> None:
    """Step 4 batch 2: pro-forma and statutory bases discriminate their atoms."""
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


def test_step4_batch2_scoped_phrases_do_not_overclaim(tax: DomainTaxonomy) -> None:
    """Batch 2 refusals: bare statutory, redeemable, parent-alone stay unmarked."""
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


def test_string_lookup_step2_rollforward_movement_modifiers(
    tax: DomainTaxonomy,
) -> None:
    """Step 2: view-consumed residual tokens are now declared modifiers.

    The specimen concepts decompose with no intent-bearing residuals.
    """
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


def test_string_lookup_step3_other_change_and_post_tax_phrases(
    tax: DomainTaxonomy,
) -> None:
    """Step 3: other-change name shapes and the after-reclassification
    phrasing decompose to their declared modifiers.
    """
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


def test_facade_view_specimens_decompose_to_gate_coordinates(
    tax: DomainTaxonomy,
) -> None:
    """Facade Step 3: long names the views gate on decompose as pinned,
    with residuals pinned exactly as the vocabulary-gap record.
    """
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
