"""Unit tests for TokenLexicon greedy phrase matching and roles."""

from edgar_sec.engine.xbrl.normalize.lexicon import LexiconEntry, TokenLexicon


def test_lexicon_longest_phrase_matching() -> None:
    """Verify greedy longest-phrase matching over multi-word tokens."""
    entries = (
        LexiconEntry(("research",), "MODIFIER", "M_RESEARCH"),
        LexiconEntry(("research", "and", "development"), "MODIFIER", "M_RD"),
        LexiconEntry(("expense",), "HEAD", "H_EXPENSE"),
    )
    lex = TokenLexicon(entries)
    tokens = ("Research", "And", "Development", "Expense")
    matches, residuals = lex.scan_tokens(tokens)

    assert len(matches) == 2
    assert matches[0].entry.atom == "M_RD"
    assert matches[1].entry.atom == "H_EXPENSE"
    assert residuals == []


def test_lexicon_entry_carries_derivation_declaration() -> None:
    """A derivation declared in data loads onto the entry, defaulting to None."""
    entry = LexiconEntry.from_dict(
        {
            "phrase": ["Due", "In"],
            "role": "MODIFIER",
            "atom": "M_MATURITY",
            "derivation": "due_in_window",
        }
    )
    assert entry.derivation == "due_in_window"
    plain = LexiconEntry.from_dict({"phrase": ["Due"], "role": "MODIFIER"})
    assert plain.derivation is None


def test_lexicon_residuals_extraction() -> None:
    """Verify unmatched tokens are returned as residuals."""
    entries = (
        LexiconEntry(("revenue",), "HEAD", "H_REVENUE"),
        LexiconEntry(("net",), "NETTING", "V_NET"),
    )
    lex = TokenLexicon(entries)
    tokens = ("Foo", "Bar", "Revenue", "Net")
    matches, residuals = lex.scan_tokens(tokens)

    assert len(matches) == 2
    assert residuals == ["Foo", "Bar"]
