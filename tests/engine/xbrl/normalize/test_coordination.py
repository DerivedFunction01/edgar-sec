"""Unit tests for the coordination operator over unspanned `and` coordinations."""

from edgar_sec.engine.xbrl.normalize.decomposer import (
    decompose_concept,
    decompose_concept_expression,
)
from edgar_sec.engine.xbrl.taxonomy.domain import DomainTaxonomy


def test_coordination_expression_preserves_both_operand_atoms(
    tax: DomainTaxonomy,
) -> None:
    """A cross-side coordination headlines today's pick; the rest are operands."""
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


def test_coordination_expression_matches_carry_both_operands(
    tax: DomainTaxonomy,
) -> None:
    """Coordination provenance spans both conjuncts, in full-token coordinates."""
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


def test_coordination_chains_multiple_operators(tax: DomainTaxonomy) -> None:
    """Two unspanned `and`s chain into a headline plus two operands."""
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


def test_coordination_agreeing_segments_fold_without_operands(
    tax: DomainTaxonomy,
) -> None:
    """Same-head conjuncts fold into the headline atom, as the flat path did."""
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


def test_coordination_authored_phrase_keeps_flat_reading(tax: DomainTaxonomy) -> None:
    """An authored and-phrase spans the coordination; no operator engages."""
    assert tax.token_lexicon is not None

    expression = decompose_concept_expression(
        "us-gaap:CashAndCashEquivalentsAtCarryingValue", tax.token_lexicon
    )
    assert expression.operator is None
    assert expression.atom.head == "H_CASH"
    assert expression.atom.modifiers == frozenset({"M_CARRYING_AMOUNT"})


def test_coordination_trailing_shared_modifier_stays_in_headline(
    tax: DomainTaxonomy,
) -> None:
    """The trailing Current of a same-head coordination stays in the headline."""
    assert tax.token_lexicon is not None

    expression = decompose_concept_expression(
        "CLDI:AccruedExpensesAndOtherLiabilitiesCurrent", tax.token_lexicon
    )
    assert expression.operator == "COORDINATION"
    assert expression.atom.head == "H_LIABILITY"
    assert expression.atom.modifiers == frozenset({"M_CURRENT", "M_OTHER"})
    assert expression.operands[1].head == "H_EXPENSE"


def test_coordination_battery_cross_side_specimens(tax: DomainTaxonomy) -> None:
    """Battery D2 specimens: foreign carriage purged, conjuncts as operands."""
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


def test_coordination_battery_leak_shape_resolves(tax: DomainTaxonomy) -> None:
    """The NotePayableAndNotesReceivable leak shape loses its headline M_DEBT."""
    assert tax.token_lexicon is not None

    expression = decompose_concept_expression(
        "x:NotePayableAndNotesReceivable", tax.token_lexicon
    )
    assert expression.operator == "COORDINATION"
    assert expression.atom.head == "H_ASSET"
    assert expression.atom.modifiers == frozenset({"M_RECEIVABLE"})
    assert expression.operands[1].head == "H_LIABILITY"
    assert expression.operands[1].modifiers == frozenset({"M_DEBT"})


def test_coordination_battery_nary_fold_keeps_headline(tax: DomainTaxonomy) -> None:
    """Battery #20: agreeing headed segments fold; the headless one records D1."""
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


def test_coordination_net_of_name_keeps_net_of_operator(tax: DomainTaxonomy) -> None:
    """A NET_OF name carrying an `and` decomposes exactly as the NET_OF path."""
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


def test_first_head_match_skips_qualifier_for_winner() -> None:
    """The coordination winner scan ignores rank-zero qualifier head claims."""
    from edgar_sec.engine.xbrl.normalize.flat import _first_head_match
    from edgar_sec.engine.xbrl.normalize.lexicon import LexiconEntry, LexiconMatch

    def match(entry: LexiconEntry, start: int) -> LexiconMatch:
        return LexiconMatch(start, start + len(entry.phrase), entry)

    qualifier = match(
        LexiconEntry(
            phrase=("q",), claim="head", head="H_UNIT", claim_class="COMPOUND_QUALIFIER"
        ),
        0,
    )
    winner = match(
        LexiconEntry(phrase=("w",), claim="head", head="H_DEBT", claim_class="TAIL"), 1
    )
    assert _first_head_match([qualifier, winner]) is winner
    assert _first_head_match([qualifier]) is None
