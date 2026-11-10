"""Unit tests for the coordination operator over unspanned `and` coordinations."""

from edgar_sec.engine.xbrl.normalize.decomposer import (
    decompose_concept,
    decompose_concept_expression,
)
from edgar_sec.engine.xbrl.taxonomy.domain import load_domain_taxonomy


def test_coordination_expression_preserves_both_operand_atoms() -> None:
    """A cross-side coordination headlines today's pick; the rest are operands."""
    tax = load_domain_taxonomy()
    assert tax.token_lexicon is not None

    expression = decompose_concept_expression(
        "ACMC:MortgageLoansReceivableAndBondPortfolioTextBlock", tax.token_lexicon
    )
    assert expression.operator == "COORDINATION"
    assert expression.operands[0].head == "H_LIABILITY"
    assert expression.operands[0].modifiers == frozenset({"M_DEBT"})
    assert expression.operands[1].head == "H_ASSET"
    assert expression.operands[1].modifiers == frozenset({"M_LOAN"})
    assert expression.weights == (1.0, 1.0)
    assert expression.atom.head == "H_LIABILITY"
    assert expression.atom.modifiers == frozenset({"M_DEBT"})
    assert expression.relations == (("COORDINATION", expression.operands[1]),)


def test_coordination_expression_matches_carry_both_operands() -> None:
    """Coordination provenance spans both conjuncts, in full-token coordinates."""
    tax = load_domain_taxonomy()
    assert tax.token_lexicon is not None

    expression = decompose_concept_expression(
        "ACMC:MortgageLoansReceivableAndBondPortfolioTextBlock", tax.token_lexicon
    )
    and_matches = [m for m in expression.matches if m.entry.phrase == ("and",)]
    assert [(m.start, m.end) for m in and_matches] == [(3, 4)]
    assert and_matches[0].entry.claim == "relation"
    assert and_matches[0].entry.relation == "COORDINATION"
    assert all(
        expression.matches[i].start <= expression.matches[i + 1].start
        for i in range(len(expression.matches) - 1)
    )


def test_coordination_chains_multiple_operators() -> None:
    """Two unspanned `and`s chain into a headline plus two operands."""
    tax = load_domain_taxonomy()
    assert tax.token_lexicon is not None

    expression = decompose_concept_expression(
        "abb:ReceivablesNetAndContractAssetsAndLiabilitiesTextBlock",
        tax.token_lexicon,
    )
    assert expression.operator == "COORDINATION"
    assert [o.head for o in expression.operands] == [
        "H_LIABILITY",
        "H_ASSET",
        "H_ASSET",
    ]
    assert expression.weights == (1.0, 1.0, 1.0)
    assert [kind for kind, _ in expression.relations] == [
        "COORDINATION",
        "COORDINATION",
    ]


def test_coordination_agreeing_segments_fold_without_operands() -> None:
    """Same-head conjuncts fold into the headline atom, as the flat path did."""
    tax = load_domain_taxonomy()
    assert tax.token_lexicon is not None

    expression = decompose_concept_expression(
        "us-gaap:InterestAndDividendsPayable", tax.token_lexicon
    )
    atom, residuals, _, _ = decompose_concept(
        "us-gaap:InterestAndDividendsPayable", tax.token_lexicon
    )
    assert expression.operator is None
    assert expression.operands == (atom,)
    assert atom.head == "H_LIABILITY"
    assert atom.modifiers == frozenset({"M_DIVIDEND", "M_INTEREST"})
    assert residuals == ()


def test_coordination_authored_phrase_keeps_flat_reading() -> None:
    """An authored and-phrase spans the coordination; no operator engages."""
    tax = load_domain_taxonomy()
    assert tax.token_lexicon is not None

    expression = decompose_concept_expression(
        "us-gaap:CashAndCashEquivalentsAtCarryingValue", tax.token_lexicon
    )
    assert expression.operator is None
    assert expression.atom.head == "H_CASH"
    assert expression.atom.modifiers == frozenset({"M_CARRYING_AMOUNT"})


def test_coordination_trailing_shared_modifier_stays_in_headline() -> None:
    """The trailing Current of a same-head coordination stays in the headline."""
    tax = load_domain_taxonomy()
    assert tax.token_lexicon is not None

    expression = decompose_concept_expression(
        "CLDI:AccruedExpensesAndOtherLiabilitiesCurrent", tax.token_lexicon
    )
    assert expression.operator == "COORDINATION"
    assert expression.atom.head == "H_LIABILITY"
    assert expression.atom.modifiers == frozenset({"M_CURRENT", "M_OTHER"})
    assert expression.operands[1].head == "H_EXPENSE"


def test_coordination_battery_cross_side_specimens() -> None:
    """Battery D2 specimens: foreign carriage purged, conjuncts as operands."""
    tax = load_domain_taxonomy()
    assert tax.token_lexicon is not None

    notes_payable = decompose_concept_expression(
        "x:NotesPayableAndReceivables", tax.token_lexicon
    )
    assert notes_payable.operator == "COORDINATION"
    assert notes_payable.atom.head == "H_ASSET"
    assert "M_DEBT" not in notes_payable.atom.modifiers
    assert notes_payable.operands[1].head == "H_LIABILITY"
    assert notes_payable.operands[1].modifiers == frozenset({"M_DEBT"})

    net_mirror = decompose_concept_expression(
        "x:AccountsReceivableAndNotesPayableNet", tax.token_lexicon
    )
    assert net_mirror.atom.head == "H_LIABILITY"
    assert net_mirror.atom.modifiers == frozenset({"M_DEBT", "V_NET"})
    assert net_mirror.operands[1].head == "H_ASSET"
    assert net_mirror.operands[1].modifiers == frozenset({"M_RECEIVABLE"})


def test_coordination_battery_leak_shape_resolves() -> None:
    """The NotePayableAndNotesReceivable leak shape loses its headline M_DEBT."""
    tax = load_domain_taxonomy()
    assert tax.token_lexicon is not None

    expression = decompose_concept_expression(
        "x:NotePayableAndNotesReceivable", tax.token_lexicon
    )
    assert expression.operator == "COORDINATION"
    assert expression.atom.head == "H_ASSET"
    assert expression.atom.modifiers == frozenset({"M_RECEIVABLE"})
    assert expression.operands[1].head == "H_LIABILITY"
    assert expression.operands[1].modifiers == frozenset({"M_DEBT"})


def test_coordination_battery_nary_fold_keeps_headline() -> None:
    """Battery #20: agreeing headed segments fold; the headless one records D1."""
    tax = load_domain_taxonomy()
    assert tax.token_lexicon is not None

    expression = decompose_concept_expression(
        "x:NotesAndAccountsPayableAndAccruedLiabilities", tax.token_lexicon
    )
    assert expression.operator is None
    assert expression.atom.head == "H_LIABILITY"
    assert expression.atom.modifiers == frozenset(
        {"M_ACCOUNTS_PAYABLE", "M_ACCRUED_LIABILITY"}
    )
    assert expression.residuals == ("Notes",)


def test_coordination_net_of_name_keeps_net_of_operator() -> None:
    """A NET_OF name carrying an `and` decomposes exactly as the NET_OF path."""
    tax = load_domain_taxonomy()
    assert tax.token_lexicon is not None

    expression = decompose_concept_expression(
        "MOBQ:CommonStockAndPrefundedWarrantsIssuedUnderPublicOffering"
        "NetOfIssuanceCostsShares",
        tax.token_lexicon,
    )
    assert expression.operator == "NET_OF"
    assert expression.operands[0].head == "H_SHARE"
    assert expression.operands[0].modifiers == frozenset({"M_COMMON"})
    assert expression.operands[1].head == "H_SHARE"
    assert expression.operands[1].modifiers == frozenset({"M_ISSUANCE"})
    assert expression.weights == (1.0, -1.0)
