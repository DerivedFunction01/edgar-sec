from __future__ import annotations

from edgar_sec.domain.forms.common.forward_looking import FORWARD_LOOKING_TERMS
from edgar_sec.domain.forms.families.current.evidence import (
    CURRENT_BODY_LEXICAL_PACK,
    CURRENT_BODY_PHRASES,
    CURRENT_BODY_STRONG_TERMS,
    CURRENT_BODY_WEAK_TERMS,
    CURRENT_COVER_EXCLUSION_TERMS,
    CURRENT_TITLES,
    CurrentReportEvidence,
)
from edgar_sec.foundation.text.automaton import CaseMode


def test_current_evidence_terms() -> None:
    assert len(CURRENT_BODY_PHRASES) > 0
    assert len(CURRENT_BODY_STRONG_TERMS) > 0
    assert len(CURRENT_BODY_WEAK_TERMS) > 0
    assert len(CURRENT_TITLES) > 0
    assert "material definitive agreement" in CURRENT_BODY_PHRASES
    assert "press release dated" in CURRENT_BODY_PHRASES
    assert "agreement" in CURRENT_BODY_STRONG_TERMS
    assert "current" in CURRENT_COVER_EXCLUSION_TERMS


def test_current_evidence_model() -> None:
    evidence = CurrentReportEvidence()
    assert len(evidence.body_ngrams) > 0
    assert len(evidence.body_verbs) > 0
    assert len(evidence.body_terms) > 0
    assert len(evidence.cover_terms) > 0


def test_current_lexical_pack_declares_all_four_tiers_in_order() -> None:
    assert CURRENT_BODY_LEXICAL_PACK.name == "current_body_start"
    tiers = CURRENT_BODY_LEXICAL_PACK.tiers
    assert tuple(tier.name for tier in tiers) == (
        "body_phrases",
        "body_strong",
        "body_forward",
        "body_weak",
    )
    assert tuple((tier.priority, tier.value) for tier in tiers) == (
        (30, 2),
        (20, 2),
        (20, 2),
        (10, 1),
    )
    assert tuple(
        (tier.terms, tier.match_kind, tier.min_distinct_hits) for tier in tiers
    ) == (
        (CURRENT_BODY_PHRASES, "ngram", 1),
        (CURRENT_BODY_STRONG_TERMS, "unigram", 2),
        (FORWARD_LOOKING_TERMS, "unigram", 2),
        (CURRENT_BODY_WEAK_TERMS, "unigram", 2),
    )
    assert tuple(tier.case_mode for tier in tiers) == (
        CaseMode.FOLD,
        CaseMode.FOLD,
        CaseMode.LOWERCASE,
        CaseMode.FOLD,
    )
    assert all(tier.support is False for tier in tiers)


def test_current_lexical_pack_has_exclusions() -> None:
    assert CURRENT_BODY_LEXICAL_PACK.exclusion_terms == CURRENT_COVER_EXCLUSION_TERMS


def test_current_evidence_model_attaches_the_lexical_pack() -> None:
    assert CurrentReportEvidence().body_lexical is CURRENT_BODY_LEXICAL_PACK
