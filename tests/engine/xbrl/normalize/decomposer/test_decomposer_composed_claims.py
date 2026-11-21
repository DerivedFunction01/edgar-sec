"""Decomposer tests: scoped head claims composed from pieces."""

from edgar_sec.engine.xbrl.normalize.decomposer import (
    decompose_concept,
    decompose_concept_expression,
)
from edgar_sec.engine.xbrl.taxonomy.domain import DomainTaxonomy


def test_repayment_of_deposits_decomposes_from_pieces(tax: DomainTaxonomy) -> None:
    """Repayment + Of + the deposit phrase compose the cash-flow atom."""
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


def test_beneficial_interest_share_datum_decomposes_from_pieces(
    tax: DomainTaxonomy,
) -> None:
    """Scoped Beneficial Interest + Shares compose the share datum."""
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


def test_maximum_percentage_of_beneficial_interest_decomposes(
    tax: DomainTaxonomy,
) -> None:
    """Maximum Percentage claims the rate head over the scoped subject."""
    assert tax.token_lexicon is not None
    atom, res, _, _ = decompose_concept(
        "pld:MaximumPercentageOfBeneficialInterestOfOutstandingShares",
        tax.token_lexicon,
    )
    assert res == ("Outstanding",)
    assert atom.head == "H_UNIT_RATE"
    assert atom.modifiers == frozenset({"M_PERCENT"})


def test_stock_conversion_rate_decomposes_from_pieces(tax: DomainTaxonomy) -> None:
    """Conversion Of Stock + Conversion Rate compose the rate datum."""
    assert tax.token_lexicon is not None
    atom, res, _, _ = decompose_concept(
        "jpm:ConversionOfStockConversionRate", tax.token_lexicon
    )
    assert res == ()
    assert atom.head == "H_UNIT_RATE"
    assert atom.modifiers == frozenset()
    reordered, _, _, _ = decompose_concept("x:ConversionRateOfStock", tax.token_lexicon)
    assert reordered == atom


def test_conversion_rate_adjustment_amounts_keep_their_heads(
    tax: DomainTaxonomy,
) -> None:
    """A Conversion Rate Adjustment names an amount, not the rate."""
    assert tax.token_lexicon is not None
    adjustment, _, _, _ = decompose_concept(
        "bmy:BusinessCombinationConsiderationTransferredConversionRateAdjustment",
        tax.token_lexicon,
    )
    assert adjustment.head == "H_CASH"


def test_decommissioning_fund_payments_decompose_from_pieces(
    tax: DomainTaxonomy,
) -> None:
    """Payments To + the scoped ARO-purpose clause compose the atom."""
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


def test_insurance_contract_benefits_decompose_from_pieces(tax: DomainTaxonomy) -> None:
    """The insurance-benefits head composes under the NET_OF tail."""
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


def test_area_of_real_estate_property_decomposes_from_pieces(
    tax: DomainTaxonomy,
) -> None:
    """Area before Of claims the measure head; Real Estate the domain."""
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


def test_area_head_claim_is_scoped_to_of_phrasings(tax: DomainTaxonomy) -> None:
    """A bare Area token without Of stays unclaimed (no head capture)."""
    assert tax.token_lexicon is not None
    code, _, _, _ = decompose_concept("dei:CityAreaCode", tax.token_lexicon)
    assert code.head == "H_UNKNOWN"


def test_nuclear_fuel_amortization_decomposes_from_pieces(tax: DomainTaxonomy) -> None:
    """Other Amortization claims the expense head over the subject."""
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


def test_gains_losses_on_loans_held_for_sale_decomposes(tax: DomainTaxonomy) -> None:
    """Gains + Losses On boundary + the loan phrase compose the atom."""
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


def test_repayment_head_claim_is_scoped_to_of_captions(tax: DomainTaxonomy) -> None:
    """Schedule nouns named Repayment keep their balance-sheet heads."""
    assert tax.token_lexicon is not None
    installments, _, _, _ = decompose_concept(
        "alb:DebtInstrumentRepaymentInstallments", tax.token_lexicon
    )
    assert installments.head == "H_LIABILITY"
    early, _, _, _ = decompose_concept(
        "us-gaap:EarlyRepaymentOfSeniorDebt", tax.token_lexicon
    )
    assert early.head == "H_CASH"


def test_due_windows_derive_bucket_horizons(tax: DomainTaxonomy) -> None:
    """Due-in and due-within windows derive the bucket horizon arithmetically."""
    assert tax.token_lexicon is not None
    cases = {
        "us-gaap:LongTermDebtMaturitiesDueInFiveYears": "M_NONCURRENT",
        "us-gaap:ContractualObligationDueInSecondYear": "M_NONCURRENT",
        "us-gaap:AccrualForEnvironmentalLossContingenciesUndiscountedDueWithinOneYear": "M_CURRENT",
    }
    for qname, expected in cases.items():
        expression = decompose_concept_expression(qname, tax.token_lexicon)
        assert expression.derived_horizon == expected, qname


def test_schedule_pair_shares_atom_but_derives_opposite_horizons(
    tax: DomainTaxonomy,
) -> None:
    """NextTwelveMonths vs AfterYearFive: one atom, opposite derivations."""
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


def test_tenor_and_classification_compose_without_derivation(
    tax: DomainTaxonomy,
) -> None:
    """Tenor alone derives nothing; an explicit classification word stands."""
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
