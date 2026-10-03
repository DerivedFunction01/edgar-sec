from __future__ import annotations

from edgar_sec.domain.forms.families.annual.evidence import (
    ANNUAL_ADDITIONAL_PHRASE_RULES,
    ANNUAL_BODY_FORWARD_TERMS,
    ANNUAL_BODY_GENERAL_TERMS,
    ANNUAL_BODY_HEADER_PHRASES,
    ANNUAL_BODY_HEADER_TERMS,
    ANNUAL_BODY_LEXICAL_PACK,
    ANNUAL_BODY_PHRASES,
    ANNUAL_BODY_SOFT_PHRASES,
    ANNUAL_BODY_STRONG_TERMS,
    ANNUAL_BODY_VERBS,
    ANNUAL_BODY_WEAK_TERMS,
    ANNUAL_COVER_EXCLUSION_TERMS,
    ANNUAL_REPORT_TITLES,
    ANNUAL_TARGET_EXHIBITS,
    BANKRUPTCY_PROCEEDINGS_TERMS,
    DELINQUENT_FILERS_TERMS,
    INCORPORATED_REFERENCE_TERMS,
    PUBLIC_FLOAT_ANCHOR_RE,
    PUBLIC_FLOAT_EXACT_RE,
    PUBLIC_FLOAT_PHRASES,
    PUBLIC_FLOAT_VALUE_RE,
    SHARES_ANCHOR_RE,
    SHARES_PHRASES,
    SHARES_VALUE_RE,
    AnnualReportEvidence,
)
from edgar_sec.foundation.text.automaton import CaseMode

ANNUAL_TIER_NAMES = (
    "body_phrase",
    "body_strong",
    "body_forward",
    "body_header",
    "body_header_phrase",
    "body_phrase_soft",
    "body_general",
    "body_weak",
)


def test_annual_evidence_terms_populated() -> None:
    assert len(ANNUAL_BODY_PHRASES) > 0
    assert len(ANNUAL_BODY_SOFT_PHRASES) > 0
    assert len(ANNUAL_BODY_STRONG_TERMS) > 0
    assert len(ANNUAL_BODY_VERBS) > 0
    assert len(ANNUAL_BODY_WEAK_TERMS) > 0
    assert len(ANNUAL_BODY_FORWARD_TERMS) > 0
    assert len(ANNUAL_BODY_GENERAL_TERMS) > 0
    assert len(ANNUAL_COVER_EXCLUSION_TERMS) > 0
    assert len(ANNUAL_REPORT_TITLES) > 0
    assert len(ANNUAL_TARGET_EXHIBITS) > 0
    assert len(DELINQUENT_FILERS_TERMS) > 0
    assert len(BANKRUPTCY_PROCEEDINGS_TERMS) > 0
    assert len(INCORPORATED_REFERENCE_TERMS) > 0
    assert len(ANNUAL_ADDITIONAL_PHRASE_RULES) > 0


def test_public_float_regexes() -> None:
    assert PUBLIC_FLOAT_ANCHOR_RE.search(PUBLIC_FLOAT_PHRASES[0])
    assert PUBLIC_FLOAT_VALUE_RE.search("$1,234,567,890")
    assert PUBLIC_FLOAT_VALUE_RE.search("500 million dollars")
    assert PUBLIC_FLOAT_EXACT_RE.search("$1,234,567")


def test_shares_regexes() -> None:
    assert SHARES_ANCHOR_RE.search(SHARES_PHRASES[0])
    assert SHARES_VALUE_RE.search("100,000,000 shares")
    assert SHARES_VALUE_RE.search("1234567")


def test_annual_report_evidence_model() -> None:
    evidence = AnnualReportEvidence()
    assert len(evidence.body_ngrams) > 0
    assert len(evidence.semantic_headings) > 0
    assert len(evidence.healing_rules) > 0


def test_lexical_pack_declares_all_eight_tiers_in_order() -> None:
    """The tier order and policy are the contract; the boundary scores on them."""
    assert ANNUAL_BODY_LEXICAL_PACK.name == "annual_body_start"
    assert tuple(tier.name for tier in ANNUAL_BODY_LEXICAL_PACK.tiers) == (
        ANNUAL_TIER_NAMES
    )
    assert tuple(
        (tier.priority, tier.value) for tier in ANNUAL_BODY_LEXICAL_PACK.tiers
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


def test_lexical_pack_tiers_own_the_family_vocabulary() -> None:
    terms = {tier.name: tier.terms for tier in ANNUAL_BODY_LEXICAL_PACK.tiers}
    assert terms["body_phrase"] == ANNUAL_BODY_PHRASES
    assert terms["body_strong"] == ANNUAL_BODY_STRONG_TERMS
    assert terms["body_forward"] == ANNUAL_BODY_FORWARD_TERMS
    assert terms["body_header"] == ANNUAL_BODY_HEADER_TERMS
    assert terms["body_header_phrase"] == ANNUAL_BODY_HEADER_PHRASES
    assert terms["body_phrase_soft"] == ANNUAL_BODY_SOFT_PHRASES
    assert terms["body_general"] == ANNUAL_BODY_GENERAL_TERMS
    assert terms["body_weak"] == ANNUAL_BODY_WEAK_TERMS


def test_lexical_pack_match_kinds_and_hit_minimums() -> None:
    kinds = {
        tier.name: (tier.match_kind, tier.min_distinct_hits)
        for tier in ANNUAL_BODY_LEXICAL_PACK.tiers
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
    forward = ANNUAL_BODY_LEXICAL_PACK.tiers[2]
    assert forward.name == "body_forward"
    assert forward.case_mode is CaseMode.LOWERCASE
    others = [tier for tier in ANNUAL_BODY_LEXICAL_PACK.tiers if tier is not forward]
    assert all(tier.case_mode is CaseMode.FOLD for tier in others)


def test_lexical_pack_soft_phrase_tier_is_support_evidence() -> None:
    soft = ANNUAL_BODY_LEXICAL_PACK.tiers[5]
    assert soft.name == "body_phrase_soft"
    assert soft.support is True
    assert soft.value == 1
    assert all(
        tier.support is False
        for tier in ANNUAL_BODY_LEXICAL_PACK.tiers
        if tier.name != "body_phrase_soft"
    )


def test_lexical_pack_exclusions_are_the_cover_exclusion_terms() -> None:
    assert ANNUAL_BODY_LEXICAL_PACK.exclusion_terms == ANNUAL_COVER_EXCLUSION_TERMS


def test_evidence_model_attaches_the_lexical_pack() -> None:
    assert AnnualReportEvidence().body_lexical is ANNUAL_BODY_LEXICAL_PACK
