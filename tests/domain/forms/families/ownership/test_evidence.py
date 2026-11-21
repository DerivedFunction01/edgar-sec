"""Tests for Form 4 ownership family evidence, lexical pack, and vetoes."""

from __future__ import annotations

from edgar_sec.domain.forms.families.ownership.evidence import (
    FOOTNOTE_DECISIVE_PHRASES,
    FOOTNOTE_EXCLUSION_TERMS,
    FOOTNOTE_STRONG_VERBS,
    FOOTNOTE_SUPPORT_TERMS,
    FOOTNOTE_VETO_PHRASES,
    OWNERSHIP_FOOTNOTE_LEXICAL_PACK,
    OWNERSHIP_PROSE_BOILERPLATE_RULE,
    PROSE_BOILERPLATE_TERMS,
)
from edgar_sec.foundation.text.automaton import tokenize
from edgar_sec.foundation.text.evidence import (
    EvidenceContext,
    compile_evidence_pack,
    score_tokens,
)

_CTX = EvidenceContext(min_words=1)


def test_ownership_evidence_terms() -> None:
    assert len(FOOTNOTE_DECISIVE_PHRASES) > 0
    assert len(FOOTNOTE_STRONG_VERBS) > 0
    assert len(FOOTNOTE_SUPPORT_TERMS) > 0
    assert len(FOOTNOTE_EXCLUSION_TERMS) > 0
    assert len(FOOTNOTE_VETO_PHRASES) > 0
    assert "explanation of responses" in FOOTNOTE_DECISIVE_PHRASES
    assert "vesting" in FOOTNOTE_STRONG_VERBS
    assert "ticker" in FOOTNOTE_EXCLUSION_TERMS
    assert "table i" in FOOTNOTE_VETO_PHRASES


def test_prose_boilerplate_rule_owns_the_existing_ownership_vocabulary() -> None:
    phrases = {
        phrase
        for sequence in OWNERSHIP_PROSE_BOILERPLATE_RULE.sequences
        for phrase in sequence
    }

    assert OWNERSHIP_PROSE_BOILERPLATE_RULE.family_ids == frozenset({"ownership"})
    assert phrases == set(PROSE_BOILERPLATE_TERMS)


def test_ownership_footnote_lexical_pack_tiers() -> None:
    pack = OWNERSHIP_FOOTNOTE_LEXICAL_PACK
    assert pack.name == "ownership_footnote"
    assert tuple(t.name for t in pack.tiers) == (
        "footnote_decisive",
        "footnote_strong",
        "footnote_support",
    )
    assert tuple((t.priority, t.value) for t in pack.tiers) == (
        (30, 3),
        (20, 2),
        (10, 1),
    )


def test_decisive_phrases_short_circuit_with_high_confidence() -> None:
    text = "Explanation of Responses: Award of restricted stock units."
    compiled = compile_evidence_pack(OWNERSHIP_FOOTNOTE_LEXICAL_PACK)
    score = score_tokens(tokenize(text), compiled, _CTX)
    assert score.score == 3
    assert score.classification == "matched"
    assert score.confidence >= 0.90
    assert score.short_circuited is True
    assert "footnote_decisive" in score.satisfied_tiers


def test_veto_signals_record_exclusions_and_prevent_false_positives() -> None:
    text = "Reporting Person Issuer Trading Symbol and Ticker"
    compiled = compile_evidence_pack(OWNERSHIP_FOOTNOTE_LEXICAL_PACK)
    score = score_tokens(tokenize(text), compiled, _CTX)
    assert "ticker" in score.exclusions
    assert score.score == 0
    assert score.classification == "no_match"


def test_strong_narrative_verbs_satisfy_secondary_tier() -> None:
    text = "(1) The stock options vest in three equal annual installments."
    compiled = compile_evidence_pack(OWNERSHIP_FOOTNOTE_LEXICAL_PACK)
    score = score_tokens(tokenize(text), compiled, _CTX)
    assert score.score >= 2
    assert score.classification == "matched"
    assert "footnote_strong" in score.satisfied_tiers
