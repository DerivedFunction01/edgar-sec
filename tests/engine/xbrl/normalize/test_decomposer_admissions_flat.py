"""Decomposer tests: class admissions and flat-cover internals."""

from edgar_sec.engine.xbrl.normalize.decomposer import (
    decompose_concept,
    decompose_concept_expression,
)
from edgar_sec.engine.xbrl.normalize.flat import (
    _fallback_head,
    _first_head_match,
    _tail_assembly,
    _uncovered_tokens,
    _window_values,
)
from edgar_sec.engine.xbrl.normalize.lexicon import (
    LexiconEntry,
    LexiconMatch,
)
from edgar_sec.engine.xbrl.taxonomy.domain import DomainTaxonomy


def test_notes_debt_class_admission_and_guards(tax: DomainTaxonomy) -> None:
    """Notes decomposes as a debt-class head; receivable/disclosure stay put."""
    assert tax.token_lexicon is not None
    lex = tax.token_lexicon

    atom, residuals, _, _ = decompose_concept("us-gaap:NotePayable", lex)
    assert atom.head == "H_LIABILITY"
    assert atom.modifiers == {"M_DEBT"}
    assert residuals == ()

    atom, residuals, _, _ = decompose_concept(
        "us-gaap:AccountsAndNotesReceivableNet", lex
    )
    assert atom.head == "H_ASSET"
    assert atom.modifiers == {"M_RECEIVABLE", "V_NET"}
    assert residuals == ("Accounts",)

    atom, residuals, _, _ = decompose_concept("us-gaap:NotesToFinancialStatements", lex)
    assert atom.head == "H_UNKNOWN"
    assert atom.modifiers == frozenset()
    assert residuals == ("Notes", "To", "Financial", "Statements")

    leak = decompose_concept_expression("acme:NotePayableAndNotesReceivable", lex)
    assert leak.atom.head == "H_ASSET"
    assert leak.atom.modifiers == {"M_RECEIVABLE"}
    assert leak.operands[1].head == "H_LIABILITY"
    assert leak.operands[1].modifiers == {"M_DEBT"}


def test_rp_partner_compound_admissions(tax: DomainTaxonomy) -> None:
    """R/P partner compounds decompose with their class identity asserted."""
    assert tax.token_lexicon is not None
    lex = tax.token_lexicon

    atom, residuals, _, _ = decompose_concept("ifrs-full:TradeReceivables", lex)
    assert atom.head == "H_ASSET"
    assert atom.modifiers == {"M_RECEIVABLE"}
    assert residuals == ()

    atom, residuals, _, _ = decompose_concept("ITMSF:TradePayables", lex)
    assert atom.head == "H_LIABILITY"
    assert atom.modifiers == {"M_ACCOUNTS_PAYABLE"}
    assert residuals == ()

    atom, residuals, _, _ = decompose_concept("cat:FinanceReceivablesNet", lex)
    assert atom.head == "H_ASSET"
    assert atom.modifiers == {"M_FINANCING_RECEIVABLE", "V_NET"}
    assert residuals == ()

    atom, residuals, _, _ = decompose_concept("us-gaap:OtherReceivables", lex)
    assert atom.head == "H_ASSET"
    assert atom.modifiers == {"M_OTHER"}
    assert residuals == ()

    atom, residuals, _, _ = decompose_concept("us-gaap:OtherIncome", lex)
    assert atom.head == "H_INCOME"
    assert atom.modifiers == {"M_OTHER"}
    assert residuals == ()

    atom, residuals, _, _ = decompose_concept("ifrs-full:TradeAndOtherReceivables", lex)
    assert atom.head == "H_ASSET"
    assert atom.modifiers == {"M_OTHER"}
    assert residuals == ("Trade",)

    atom, residuals, _, _ = decompose_concept("us-gaap:ManagementFeePayable", lex)
    assert atom.head == "H_LIABILITY"
    assert atom.modifiers == frozenset()
    assert residuals == ("Management",)

    atom, residuals, _, _ = decompose_concept(
        "hmr:BusinessAcquisitionInstallmentsPayable", lex
    )
    assert atom.head == "H_LIABILITY"
    assert atom.modifiers == {"M_BUSINESS_COMBINATION"}
    assert residuals == ()

    atom, residuals, _, _ = decompose_concept("ipa:AmountsReceivableNet", lex)
    assert atom.head == "H_ASSET"
    assert atom.modifiers == {"M_RECEIVABLE", "V_NET"}
    assert residuals == ()

    atom, residuals, _, _ = decompose_concept("ry:NotionalAmounts", lex)
    assert atom.head == "H_COMMITMENT"
    assert atom.modifiers == {"M_NOTIONAL_AMOUNT"}
    assert residuals == ()

    atom, residuals, _, _ = decompose_concept("chnr:TotalOthersPayables", lex)
    assert atom.head == "H_LIABILITY"
    assert atom.modifiers == frozenset()
    assert residuals == ("Total", "Others")


def _match(entry: LexiconEntry, start: int = 0) -> LexiconMatch:
    return LexiconMatch(start, start + len(entry.phrase), entry)


def test_window_values_edges() -> None:
    """Windows re-base to their start; the end is exclusive, absence is open."""
    values = {0: 5, 2: 7, 4: 9}
    assert _window_values(values, 2, 4) == {0: 7}
    assert _window_values(values, 2) == {0: 7, 2: 9}
    assert _window_values(values, 0) == values
    assert _window_values(values, 6) == {}
    assert _window_values({}, 0, 3) == {}


def test_uncovered_tokens_span_shapes() -> None:
    """No spans leaves every token; a full cover leaves none."""
    tokens = ("Alpha", "Beta", "Gamma")
    assert _uncovered_tokens(tokens, []) == ["Alpha", "Beta", "Gamma"]
    assert _uncovered_tokens(tokens, [(0, 3)]) == []
    assert _uncovered_tokens(tokens, [(0, 1), (2, 3)]) == ["Beta"]
    assert _uncovered_tokens((), [(0, 1)]) == []


def test_first_head_match_and_fallback_shapes() -> None:
    """The fallback takes the first positional positive-rank head claim."""
    qualifier = _match(
        LexiconEntry(
            phrase=("q",), claim="head", head="H_UNIT", claim_class="COMPOUND_QUALIFIER"
        )
    )
    modifier = _match(LexiconEntry(phrase=("m",), claim="modifier", atom="M_X"))
    primary = _match(
        LexiconEntry(
            phrase=("p",), claim="head", head="H_ASSET", claim_class="PRIMARY"
        ),
        start=2,
    )
    tail = _match(
        LexiconEntry(phrase=("t",), claim="head", head="H_CASH", claim_class="TAIL"),
        start=3,
    )
    assert _first_head_match([qualifier, modifier, primary, tail]) is primary
    assert _first_head_match([qualifier, modifier]) is None
    assert _fallback_head([qualifier, tail, primary]) == "H_CASH"
    assert _fallback_head([]) == "UNKNOWN"


def test_tail_assembly_direction_and_indexicals() -> None:
    """Direction is the first directed claim; indexicals extend the base."""
    directed = _match(LexiconEntry(phrase=("d",), claim="modifier", direction=-1.0))
    later = _match(
        LexiconEntry(phrase=("e",), claim="modifier", direction=1.0), start=1
    )
    indexical = _match(
        LexiconEntry(phrase=("i",), claim="indexical", indexical="IX_PER_SHARE"),
        start=2,
    )
    direction, indexicals, derived, temporal = _tail_assembly(
        ("D", "E", "I"), [directed, later, indexical], ("IX_BASE",), {}, {}
    )
    assert direction == -1.0
    assert indexicals == ("IX_BASE", "IX_PER_SHARE")
    assert derived is None and temporal is None
    direction, indexicals, _, _ = _tail_assembly(("D",), [later], (), {}, {})
    assert direction == 1.0 and indexicals == ()
