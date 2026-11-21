from __future__ import annotations

from edgar_sec.domain.forms.common.forward_looking import FORWARD_LOOKING_TERMS
from edgar_sec.domain.forms.families.quarterly.evidence import (
    QUARTERLY_BODY_LEXICAL_PACK,
    QUARTERLY_BODY_PHRASES,
    QUARTERLY_BODY_STRONG_TERMS,
    QUARTERLY_BODY_WEAK_TERMS,
    QUARTERLY_COVER_EXCLUSION_TERMS,
    QuarterlyReportEvidence,
)
from edgar_sec.foundation.text.automaton import CaseMode


def test_quarterly_evidence_terms() -> None:
    assert len(QUARTERLY_BODY_PHRASES) > 0
    assert len(QUARTERLY_BODY_STRONG_TERMS) > 0
    assert len(QUARTERLY_BODY_WEAK_TERMS) > 0
    assert "three months ended" in QUARTERLY_BODY_PHRASES
    assert "interim" in QUARTERLY_BODY_STRONG_TERMS
    assert "decreased" in QUARTERLY_BODY_WEAK_TERMS
    assert "quarterly" in QUARTERLY_COVER_EXCLUSION_TERMS


def test_quarterly_evidence_model() -> None:
    evidence = QuarterlyReportEvidence()
    assert len(evidence.body_ngrams) > 0
    assert len(evidence.body_verbs) > 0
    assert len(evidence.body_terms) > 0
    assert len(evidence.shape_terms) > 0
    assert len(evidence.healing_rules) > 0
    assert len(evidence.cover_terms) > 0


def test_quarterly_lexical_pack_declares_all_four_tiers_in_order() -> None:
    assert QUARTERLY_BODY_LEXICAL_PACK.name == "quarterly_body_start"
    tiers = QUARTERLY_BODY_LEXICAL_PACK.tiers
    assert tuple(tier.name for tier in tiers) == (
        "body_phrase",
        "body_strong",
        "body_forward",
        "body_weak",
    )
    assert tuple((tier.priority, tier.value) for tier in tiers) == (
        (30, 3),
        (20, 2),
        (20, 2),
        (10, 1),
    )
    assert tuple(
        (tier.terms, tier.match_kind, tier.min_distinct_hits) for tier in tiers
    ) == (
        (QUARTERLY_BODY_PHRASES, "ngram", 1),
        (QUARTERLY_BODY_STRONG_TERMS, "unigram", 2),
        (FORWARD_LOOKING_TERMS, "unigram", 2),
        (QUARTERLY_BODY_WEAK_TERMS, "unigram", 2),
    )
    assert tuple(tier.case_mode for tier in tiers) == (
        CaseMode.FOLD,
        CaseMode.FOLD,
        CaseMode.LOWERCASE,
        CaseMode.FOLD,
    )
    assert all(tier.support is False for tier in tiers)


def test_quarterly_lexical_pack_has_exclusions() -> None:
    assert (
        QUARTERLY_BODY_LEXICAL_PACK.exclusion_terms == QUARTERLY_COVER_EXCLUSION_TERMS
    )


def test_quarterly_evidence_model_attaches_the_lexical_pack() -> None:
    assert QuarterlyReportEvidence().body_lexical is QUARTERLY_BODY_LEXICAL_PACK
