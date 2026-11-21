"""Decomposer tests: purchase, disposal, sale, and gain frames."""

from edgar_sec.engine.xbrl.normalize.decomposer import decompose_concept
from edgar_sec.engine.xbrl.schema.models import ConceptDeclaration
from edgar_sec.engine.xbrl.taxonomy.domain import DomainTaxonomy


def test_purchase_frame_attaches_act_and_outflow_direction(tax: DomainTaxonomy) -> None:
    """Purchase-led flow lines carry the purchase act at direction -1.0."""
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


def test_purchase_frame_plural_flow_forms_carry_the_act(tax: DomainTaxonomy) -> None:
    """Plural-led flow lines take the frame direction alongside the act."""
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


def test_purchase_frame_guards_hold_stock_and_rollforward_shapes(
    tax: DomainTaxonomy,
) -> None:
    """Stock, obligation, member, and rollforward shapes keep base atoms."""
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


def test_purchase_frame_declaration_vetoes_instant_and_text(
    tax: DomainTaxonomy,
) -> None:
    """An instant or text declaration refuses the act for stock shapes."""
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


def test_purchase_frame_constructed_extension_forms(tax: DomainTaxonomy) -> None:
    """Synthetic extension names: flow forms take the act, guards refuse.

    Unattested in the corpus: categorization by construction.
    """
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


def test_purchase_frame_leaves_payments_and_proceeds_untouched(
    tax: DomainTaxonomy,
) -> None:
    """The payments and proceeds coordinates keep their own directions."""
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


def test_disposal_claims_assert_the_exit_identity(tax: DomainTaxonomy) -> None:
    """Disposal and derecognition forms carry M_DISPOSAL in every dialect."""
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


def test_sale_act_separated_from_purpose_and_goods(tax: DomainTaxonomy) -> None:
    """Sale-as-act carries M_SALE; purpose and goods senses keep their markers."""
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


def test_gain_family_carries_the_disposal_gain_identity(tax: DomainTaxonomy) -> None:
    """Gain/loss on disposal, sale, or extinguishment carries M_DISPOSAL_GAIN."""
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


def test_gain_family_from_postfix_and_arising_forms(tax: DomainTaxonomy) -> None:
    """From, postfix, and arising-from gain forms carry the gain identity."""
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


def test_gross_unrealized_positions_carry_side_markers(tax: DomainTaxonomy) -> None:
    """Gross unrealized gain and loss positions carry distinct side markers."""
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


def test_financial_assets_object_claim(tax: DomainTaxonomy) -> None:
    """Financial-asset phrases assert the instrument object on purchase lines."""
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
