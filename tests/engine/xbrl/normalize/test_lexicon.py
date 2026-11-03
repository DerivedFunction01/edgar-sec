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


def test_grammatical_frame_record_parses_act_modifier() -> None:
    """An act-declaring frame record loads its act modifier; others None."""
    from edgar_sec.engine.xbrl.taxonomy.records import GrammaticalFrame

    frame = GrammaticalFrame.from_dict(
        {
            "frame_id": "FRAME_OUTFLOW_PURCHASE",
            "prefix_tokens": ["purchase"],
            "direction": -1.0,
            "strip_tokens": ["to", "for", "of", "and"],
            "act_modifier": "M_PURCHASE",
        }
    )
    assert frame.act_modifier == "M_PURCHASE"
    plain = GrammaticalFrame.from_dict(
        {"frame_id": "FRAME_INFLOW_PROCEEDS_FROM", "prefix_tokens": ["proceeds"]}
    )
    assert plain.act_modifier is None


def test_lexicon_frame_attachment_and_matching() -> None:
    """Attached frames match on leading tokens, in declaration order."""
    from edgar_sec.engine.xbrl.taxonomy.records import GrammaticalFrame

    lex = TokenLexicon(())
    assert lex.match_grammatical_frame(("Purchase", "Of", "Assets")) is None
    lex.attach_grammatical_frames(
        (
            GrammaticalFrame("FRAME_A", ("payments", "to"), direction=-1.0),
            GrammaticalFrame(
                "FRAME_B", ("purchase",), direction=-1.0, act_modifier="M_PURCHASE"
            ),
        )
    )
    found = lex.match_grammatical_frame(("Purchase", "Of", "Assets"))
    assert found is not None and found.frame_id == "FRAME_B"
    assert lex.match_grammatical_frame(("Sale", "Of", "Assets")) is None


def test_loaded_taxonomy_attaches_purchase_frames_to_lexicon() -> None:
    """The shipped purchase frames reach the lexicon with their act."""
    from edgar_sec.engine.xbrl.taxonomy.domain import load_domain_taxonomy

    tax = load_domain_taxonomy()
    assert tax.token_lexicon is not None
    frame = tax.token_lexicon.match_grammatical_frame(("Purchases", "Of", "Debt"))
    assert frame is not None
    assert frame.act_modifier == "M_PURCHASE"
    assert frame.direction == -1.0
