from __future__ import annotations

from edgar_sec.domain.forms.families.registration.evidence import (
    REGISTRATION_BODY_FORWARD_TERMS,
    REGISTRATION_BODY_GENERAL_TERMS,
    REGISTRATION_BODY_HEADER_PHRASES,
    REGISTRATION_BODY_HEADER_TERMS,
    REGISTRATION_BODY_LEXICAL_PACK,
    REGISTRATION_BODY_PHRASES,
    REGISTRATION_BODY_SOFT_PHRASES,
    REGISTRATION_BODY_STRONG_TERMS,
    REGISTRATION_BODY_VERBS,
    REGISTRATION_BODY_WEAK_TERMS,
    REGISTRATION_COVER_EXCLUSION_TERMS,
    REGISTRATION_REPORT_TITLES,
    REGISTRATION_SHAPE_TERMS,
    RegistrationEvidence,
    S3_REPORT_TITLES,
    S4_REPORT_TITLES,
    S8_REPORT_TITLES,
)
from edgar_sec.foundation.text.automaton import CaseMode
from edgar_sec.foundation.text.evidence import compile_evidence_pack

REGISTRATION_TIER_NAMES = (
    "body_phrase",
    "body_strong",
    "body_forward",
    "body_header",
    "body_header_phrase",
    "body_phrase_soft",
    "body_general",
    "body_weak",
)


def test_registration_evidence_terms_populated() -> None:
    assert len(REGISTRATION_BODY_PHRASES) > 0
    assert len(REGISTRATION_BODY_SOFT_PHRASES) > 0
    assert len(REGISTRATION_BODY_STRONG_TERMS) > 0
    assert len(REGISTRATION_BODY_VERBS) > 0
    assert len(REGISTRATION_BODY_WEAK_TERMS) > 0
    assert len(REGISTRATION_BODY_FORWARD_TERMS) > 0
    assert len(REGISTRATION_BODY_GENERAL_TERMS) > 0
    assert len(REGISTRATION_COVER_EXCLUSION_TERMS) > 0
    assert len(REGISTRATION_REPORT_TITLES) > 0
    assert len(S3_REPORT_TITLES) > 0
    assert len(S4_REPORT_TITLES) > 0
    assert len(S8_REPORT_TITLES) > 0
    assert len(REGISTRATION_SHAPE_TERMS) > 0


def test_registration_evidence_model() -> None:
    evidence = RegistrationEvidence()
    assert len(evidence.body_ngrams) > 0
    assert len(evidence.body_verbs) > 0
    assert len(evidence.body_terms) > 0
    assert len(evidence.cover_terms) > 0
    assert evidence.body_lexical is REGISTRATION_BODY_LEXICAL_PACK


def test_lexical_pack_declares_all_eight_tiers_in_order() -> None:
    assert REGISTRATION_BODY_LEXICAL_PACK.name == "registration_body_start"
    assert tuple(tier.name for tier in REGISTRATION_BODY_LEXICAL_PACK.tiers) == (
        REGISTRATION_TIER_NAMES
    )
    assert tuple(
        (tier.priority, tier.value) for tier in REGISTRATION_BODY_LEXICAL_PACK.tiers
    ) == (
        (30, 3),
        (20, 2),
        (20, 2),
        (20, 2),
        (20, 2),
        (15, 1),
        (10, 1),
        (10, 1),
    )


def test_lexical_pack_tiers_own_family_vocabulary() -> None:
    terms = {tier.name: tier.terms for tier in REGISTRATION_BODY_LEXICAL_PACK.tiers}
    assert terms["body_phrase"] == REGISTRATION_BODY_PHRASES
    assert terms["body_strong"] == REGISTRATION_BODY_STRONG_TERMS
    assert terms["body_forward"] == REGISTRATION_BODY_FORWARD_TERMS
    assert terms["body_header"] == REGISTRATION_BODY_HEADER_TERMS
    assert terms["body_header_phrase"] == REGISTRATION_BODY_HEADER_PHRASES
    assert terms["body_phrase_soft"] == REGISTRATION_BODY_SOFT_PHRASES
    assert terms["body_general"] == REGISTRATION_BODY_GENERAL_TERMS
    assert terms["body_weak"] == REGISTRATION_BODY_WEAK_TERMS


def test_lexical_pack_match_kinds_and_hit_minimums() -> None:
    kinds = {
        tier.name: (tier.match_kind, tier.min_distinct_hits)
        for tier in REGISTRATION_BODY_LEXICAL_PACK.tiers
    }
    assert kinds["body_phrase"] == ("ngram", 1)
    assert kinds["body_strong"] == ("unigram", 2)
    assert kinds["body_forward"] == ("unigram", 2)
    assert kinds["body_header"] == ("unigram", 2)
    assert kinds["body_header_phrase"] == ("ngram", 1)
    assert kinds["body_phrase_soft"] == ("ngram", 1)
    assert kinds["body_general"] == ("unigram", 2)
    assert kinds["body_weak"] == ("unigram", 2)


def test_lexical_pack_forward_tier_matches_lowercase_tokens_only() -> None:
    forward = REGISTRATION_BODY_LEXICAL_PACK.tiers[2]
    assert forward.name == "body_forward"
    assert forward.case_mode is CaseMode.LOWERCASE
    others = [
        tier for tier in REGISTRATION_BODY_LEXICAL_PACK.tiers if tier is not forward
    ]
    assert all(tier.case_mode is CaseMode.FOLD for tier in others)


def test_lexical_pack_soft_phrase_tier_is_support_evidence() -> None:
    soft = REGISTRATION_BODY_LEXICAL_PACK.tiers[5]
    assert soft.name == "body_phrase_soft"
    assert soft.support is True
    assert soft.value == 1
    assert all(
        tier.support is False
        for tier in REGISTRATION_BODY_LEXICAL_PACK.tiers
        if tier.name != "body_phrase_soft"
    )


def test_lexical_pack_compiles_cleanly() -> None:
    compiled = compile_evidence_pack(REGISTRATION_BODY_LEXICAL_PACK)
    assert len(compiled.tiers) == 8


def test_registration_body_phrases_exclude_toc_and_deep_matter() -> None:
    assert "table of contents" not in REGISTRATION_BODY_PHRASES
    assert "table of contents" not in REGISTRATION_BODY_HEADER_PHRASES
    assert "balance sheets" not in REGISTRATION_BODY_PHRASES
    assert "we have audited" not in REGISTRATION_BODY_PHRASES
    assert "in our opinion" not in REGISTRATION_BODY_PHRASES
    assert "we have" in REGISTRATION_BODY_PHRASES
    assert "selling stockholders" in REGISTRATION_BODY_PHRASES
