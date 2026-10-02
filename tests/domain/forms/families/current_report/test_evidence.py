"""Tests for current report evidence definitions."""

from __future__ import annotations

from edgar_sec.domain.forms.families.current_report.evidence import (
    CURRENT_REPORT_BODY_LEXICAL_PACK,
    CURRENT_REPORT_BODY_PHRASES,
    CURRENT_REPORT_BODY_STRONG_TERMS,
    CURRENT_REPORT_BODY_WEAK_TERMS,
    CurrentReportEvidence,
)
from edgar_sec.foundation.text.automaton import CaseMode


def test_current_report_evidence_terms() -> None:
    assert len(CURRENT_REPORT_BODY_PHRASES) > 0
    assert len(CURRENT_REPORT_BODY_STRONG_TERMS) > 0
    assert len(CURRENT_REPORT_BODY_WEAK_TERMS) > 0
    assert "material definitive agreement" in CURRENT_REPORT_BODY_PHRASES
    assert "agreement" in CURRENT_REPORT_BODY_STRONG_TERMS


def test_current_report_evidence_model() -> None:
    evidence = CurrentReportEvidence()
    assert len(evidence.body_ngrams) > 0
    assert len(evidence.body_verbs) > 0


def test_current_report_lexical_pack_declares_all_three_tiers_in_order() -> None:
    assert CURRENT_REPORT_BODY_LEXICAL_PACK.name == "current_report_body_start"
    tiers = CURRENT_REPORT_BODY_LEXICAL_PACK.tiers
    assert tuple(tier.name for tier in tiers) == (
        "body_phrases",
        "body_strong",
        "body_weak",
    )
    assert tuple((tier.priority, tier.value) for tier in tiers) == (
        (30, 2),
        (20, 2),
        (10, 1),
    )
    assert tuple(
        (tier.terms, tier.match_kind, tier.min_distinct_hits) for tier in tiers
    ) == (
        (CURRENT_REPORT_BODY_PHRASES, "ngram", 1),
        (CURRENT_REPORT_BODY_STRONG_TERMS, "unigram", 2),
        (CURRENT_REPORT_BODY_WEAK_TERMS, "unigram", 2),
    )
    assert all(tier.case_mode is CaseMode.FOLD for tier in tiers)
    assert all(tier.support is False for tier in tiers)


def test_current_report_lexical_pack_has_no_exclusions() -> None:
    assert CURRENT_REPORT_BODY_LEXICAL_PACK.exclusion_terms == ()


def test_current_report_evidence_model_attaches_the_lexical_pack() -> None:
    assert CurrentReportEvidence().body_lexical is CURRENT_REPORT_BODY_LEXICAL_PACK
