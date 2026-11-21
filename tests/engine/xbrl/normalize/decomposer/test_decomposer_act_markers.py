"""Decomposer tests: dedicated markers for formerly absent acts."""

from edgar_sec.engine.xbrl.normalize.decomposer import decompose_concept
from edgar_sec.engine.xbrl.taxonomy.domain import DomainTaxonomy


def test_absent_acts_carry_dedicated_markers(tax: DomainTaxonomy) -> None:
    """Each formerly absent act asserts its carrier on attested names."""
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


def test_absent_act_attribute_guards_stay_byte_identical(tax: DomainTaxonomy) -> None:
    """Attribute senses of the new acts' words keep their base atoms."""
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


def test_payments_for_origination_keeps_outflow_direction(tax: DomainTaxonomy) -> None:
    """The payments-for-origination anchor asserts the act, direction held."""
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


def test_declaration_keeps_dividend_identity_and_rate_head(tax: DomainTaxonomy) -> None:
    """Per-share declared lines gain the act; dividend and head stand."""
    assert tax.token_lexicon is not None
    lex = tax.token_lexicon

    atom, _, _, _ = decompose_concept(
        "us-gaap:CommonStockDividendsPerShareDeclared", lex
    )
    assert atom.head == "H_UNIT_RATE"
    assert atom.modifiers == {"M_COMMON", "M_DECLARATION", "M_DIVIDEND"}


def test_step5_wordform_twins_land_the_same_atom(tax: DomainTaxonomy) -> None:
    """Dialect and synonym twins of the new acts land identical atoms."""
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
