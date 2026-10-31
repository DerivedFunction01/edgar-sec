"""Unit tests for TokenLexicon greedy phrase matching and claims."""

import pytest

from edgar_sec.engine.xbrl.normalize.lexicon import LexiconEntry, TokenLexicon


def test_lexicon_longest_phrase_matching() -> None:
    """Verify greedy longest-phrase matching over multi-word tokens."""
    entries = (
        LexiconEntry(("research",), "modifier", atom="M_RESEARCH"),
        LexiconEntry(("research", "and", "development"), "modifier", atom="M_RD"),
        LexiconEntry(("expense",), "head", head="H_EXPENSE", claim_class="PRIMARY"),
    )
    lex = TokenLexicon(entries)
    tokens = ("Research", "And", "Development", "Expense")
    matches, residuals = lex.scan_tokens(tokens)

    assert len(matches) == 2
    assert matches[0].entry.claim_atom() == "M_RD"
    assert matches[1].entry.claim_atom() == "H_EXPENSE"
    assert residuals == []


def test_lexicon_entry_carries_derivation_declaration() -> None:
    """A temporal pattern declared in data loads onto the entry, defaulting to None."""
    entry = LexiconEntry.from_dict(
        {
            "phrase": ["Due", "In"],
            "claim": "modifier",
            "atom": "M_MATURITY",
            "temporal_pattern": "due_in_window",
        }
    )
    assert entry.temporal_pattern == "due_in_window"
    plain = LexiconEntry.from_dict({"phrase": ["Due"], "claim": "modifier"})
    assert plain.temporal_pattern is None


def test_lexicon_residuals_extraction() -> None:
    """Verify unmatched tokens are returned as residuals."""
    entries = (
        LexiconEntry(("revenue",), "head", head="H_REVENUE", claim_class="PRIMARY"),
        LexiconEntry(("net",), "modifier", atom="V_NET"),
    )
    lex = TokenLexicon(entries)
    tokens = ("Foo", "Bar", "Revenue", "Net")
    matches, residuals = lex.scan_tokens(tokens)

    assert len(matches) == 2
    assert residuals == ["Foo", "Bar"]


def test_head_claim_without_class_is_a_loader_error() -> None:
    """RR5: a head claim with no class, or an unknown claim kind, is refused."""
    with pytest.raises(ValueError):
        LexiconEntry.from_dict(
            {"phrase": ["Expense"], "claim": "head", "head": "H_EXPENSE"}
        )
    with pytest.raises(ValueError):
        LexiconEntry.from_dict({"phrase": ["Of"], "claim": "subordinator"})


def test_requires_evidence_claim_loads() -> None:
    """Q6 slot: an evidence-gated claim parses onto the entry."""
    entry = LexiconEntry.from_dict(
        {
            "phrase": ["Impairment"],
            "claim": "head",
            "head": "H_EXPENSE",
            "claim_class": "PRIMARY",
            "requires_evidence": True,
        }
    )
    assert entry.requires_evidence is True
