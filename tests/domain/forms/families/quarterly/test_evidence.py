"""Tests for quarterly report evidence definitions."""

from __future__ import annotations

from edgar_sec.domain.forms.families.quarterly.evidence import (
    QUARTERLY_BODY_LEXICAL_PACK,
    QUARTERLY_BODY_STRONG_TERMS,
    QUARTERLY_BODY_WEAK_TERMS,
    QuarterlyReportEvidence,
)
from edgar_sec.foundation.text.automaton import CaseMode


def test_quarterly_evidence_terms() -> None:
    assert len(QUARTERLY_BODY_STRONG_TERMS) > 0
    assert len(QUARTERLY_BODY_WEAK_TERMS) > 0
    assert "quarterly" in QUARTERLY_BODY_STRONG_TERMS
    assert "decreased" in QUARTERLY_BODY_WEAK_TERMS


def test_quarterly_evidence_model() -> None:
    evidence = QuarterlyReportEvidence()
    assert len(evidence.body_ngrams) > 0
    assert len(evidence.body_verbs) > 0


def test_quarterly_lexical_pack_declares_both_tiers_in_order() -> None:
    assert QUARTERLY_BODY_LEXICAL_PACK.name == "quarterly_body_start"
    tiers = QUARTERLY_BODY_LEXICAL_PACK.tiers
    assert tuple(tier.name for tier in tiers) == ("body_strong", "body_weak")
    assert tuple((tier.priority, tier.value) for tier in tiers) == ((20, 2), (10, 1))
    assert tuple(
        (tier.terms, tier.match_kind, tier.min_distinct_hits) for tier in tiers
    ) == (
        (QUARTERLY_BODY_STRONG_TERMS, "unigram", 2),
        (QUARTERLY_BODY_WEAK_TERMS, "unigram", 2),
    )
    assert all(tier.case_mode is CaseMode.FOLD for tier in tiers)
    assert all(tier.support is False for tier in tiers)


def test_quarterly_lexical_pack_has_no_exclusions() -> None:
    assert QUARTERLY_BODY_LEXICAL_PACK.exclusion_terms == ()


def test_quarterly_evidence_model_attaches_the_lexical_pack() -> None:
    assert QuarterlyReportEvidence().body_lexical is QUARTERLY_BODY_LEXICAL_PACK
