"""Decomposer tests: proceeds and receipts cash-head frames."""

from edgar_sec.engine.xbrl.normalize.decomposer import (
    decompose_concept,
    decompose_concept_expression,
)
from edgar_sec.engine.xbrl.taxonomy.domain import DomainTaxonomy


def test_proceeds_frame_guarantees_the_cash_head(tax: DomainTaxonomy) -> None:
    """Proceeds-led names land H_CASH; only the head moves."""
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


def test_receipts_frame_guarantees_the_cash_head(tax: DomainTaxonomy) -> None:
    """Receipts-led names land H_CASH; only the head moves."""
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


def test_proceeds_head_guarantee_leaves_other_names_untouched(
    tax: DomainTaxonomy,
) -> None:
    """No proceeds prefix, no frame: stocks and NET_OF names stand."""
    assert tax.token_lexicon is not None
    lex = tax.token_lexicon

    atom, _, _, _ = decompose_concept("acme:BorrowingsUnderSolarFinancingFacility", lex)
    assert atom.head == "H_LIABILITY"

    atom, _, direction, _ = decompose_concept(
        "us-gaap:ProceedsFromDivestitureOfBusinessesNetOfCashDivested", lex
    )
    assert atom.head == "H_CASH"
    assert direction == 1.0


def test_proceeds_debt_phrases_claim_their_direction(tax: DomainTaxonomy) -> None:
    """The specific-debt proceeds names bear direction; none is a default."""
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


def test_proceeds_census_claims_carry_the_source_acts(tax: DomainTaxonomy) -> None:
    """Issue-form and annuities proceeds carry M_ISSUANCE; guards unchanged."""
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


def test_trailing_sale_proceeds_carry_the_sale_act(tax: DomainTaxonomy) -> None:
    """The trailing Sale Proceeds form asserts M_SALE on the cash head."""
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
