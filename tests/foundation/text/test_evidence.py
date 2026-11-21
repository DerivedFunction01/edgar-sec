"""Contract tests for the lexical evidence pack engine."""

from __future__ import annotations

import pytest

from edgar_sec.foundation.text.evidence import (
    BowScore,
    EvidenceContext,
    EvidenceTier,
    LexicalEvidencePack,
    band_max_values,
    build_reason,
    compile_evidence_pack,
    normalize_tokens,
    score_unit,
)


def _pack() -> LexicalEvidencePack:
    return LexicalEvidencePack(
        name="body",
        tiers=(
            EvidenceTier(
                name="body_phrase",
                priority=30,
                value=3,
                terms=("market segments", "labor union"),
                match_kind="ngram",
                min_distinct_hits=1,
            ),
            EvidenceTier(
                name="body_strong",
                priority=20,
                value=2,
                terms=("founded", "provider", "customers"),
                min_distinct_hits=2,
            ),
            EvidenceTier(
                name="body_weak",
                priority=10,
                value=1,
                terms=("provides", "operates"),
                min_distinct_hits=2,
            ),
        ),
        exclusion_terms=("registrant",),
    )


def test_a_decisive_phrase_scores_three() -> None:
    score = score_unit(
        "The company reports distinct market segments for every region.",
        _pack(),
        EvidenceContext(),
    )

    assert score.score == 3
    assert score.classification == "matched"
    assert score.satisfied_tiers == ("body_phrase",)


def test_two_strong_unigrams_score_two() -> None:
    score = score_unit(
        "The provider was founded by its customers in the region.",
        _pack(),
        EvidenceContext(),
    )

    assert score.score == 2
    assert "body_strong" in score.satisfied_tiers


def test_one_strong_unigram_below_the_minimum_is_ambiguous() -> None:
    score = score_unit(
        "The provider operates segments and provides goods in a region today.",
        _pack(),
        EvidenceContext(),
    )

    assert score.score == 1
    assert score.classification == "ambiguous"


def test_an_ineligible_unit_scores_zero_with_the_caller_reason() -> None:
    score = score_unit(
        "market segments labor union founded provider customers provides operates",
        _pack(),
        EvidenceContext(eligible=False, exclusion_reason="inside TOC"),
    )

    assert score.score == 0
    assert score.reason == "inside TOC"


def test_a_unit_below_the_word_gate_is_not_scored() -> None:
    score = score_unit("market segments", _pack(), EvidenceContext())

    assert score.score == 0
    assert "below minimum" in score.reason


def test_exclusion_terms_alone_are_reported_without_confirming() -> None:
    score = score_unit(
        "the registrant is the registrant and the registrant here",
        _pack(),
        EvidenceContext(),
    )

    assert score.score == 0
    assert score.exclusions == ("registrant",)
    assert score.confidence == 0.2


def test_an_empty_pack_has_no_tiers() -> None:
    compiled = compile_evidence_pack(LexicalEvidencePack(name="empty"))

    assert compiled.tiers == ()
    assert score_unit("one two three four five six seven eight", compiled).reason == (
        "evidence pack 'empty' has no tiers"
    )


def test_packs_are_compiled_once_by_value() -> None:
    pack = _pack()

    assert compile_evidence_pack(pack) is compile_evidence_pack(pack)


def test_an_already_compiled_pack_is_used_directly() -> None:
    compiled = compile_evidence_pack(_pack())
    score = score_unit("market segments for the whole company today and next", compiled)

    assert isinstance(score, BowScore)
    assert score.score == 3


def test_a_support_tier_cannot_confirm_a_decision_alone() -> None:
    pack = LexicalEvidencePack(
        name="support",
        tiers=(
            EvidenceTier(
                name="soft",
                priority=10,
                value=1,
                terms=("expects",),
                support=True,
                min_distinct_hits=1,
            ),
        ),
    )
    score = score_unit("the company expects growth next year ahead of us all", pack)

    assert score.score == 1
    assert score.support_score == 1
    assert score.satisfied_tiers == ("soft",)


def test_invalid_tier_policies_are_rejected_at_declaration() -> None:
    with pytest.raises(ValueError):
        EvidenceTier(name="bad", priority=1, value=4, terms=("alpha",))
    with pytest.raises(ValueError):
        EvidenceTier(name="bad", priority=1, value=2, terms=("alpha",), support=True)
    with pytest.raises(ValueError):
        EvidenceTier(name="bad", priority=1, value=2, terms=("alpha"), match_kind="tri")
    with pytest.raises(ValueError):
        EvidenceTier(
            name="bad", priority=1, value=2, terms=("alpha"), min_distinct_hits=0
        )


def test_an_empty_tier_is_rejected_at_compile_time() -> None:
    with pytest.raises(ValueError, match="no terms"):
        compile_evidence_pack(
            LexicalEvidencePack(name="p", tiers=(EvidenceTier("t", 1, 1, ()),))
        )


def test_a_unigram_tier_term_must_tokenize_to_one_token() -> None:
    with pytest.raises(ValueError, match="one token"):
        compile_evidence_pack(
            LexicalEvidencePack(
                name="p",
                tiers=(EvidenceTier("t", 1, 1, ("two words"), match_kind="unigram"),),
            )
        )


def test_a_ngram_tier_term_must_tokenize_to_two_or_more_tokens() -> None:
    with pytest.raises(ValueError, match="two or more tokens"):
        compile_evidence_pack(
            LexicalEvidencePack(
                name="p",
                tiers=(EvidenceTier("t", 1, 1, ("solo",), match_kind="ngram"),),
            )
        )


def test_a_folded_term_may_only_be_configured_under_one_case_mode() -> None:
    with pytest.raises(ValueError, match="multiple case modes"):
        compile_evidence_pack(
            LexicalEvidencePack(
                name="p",
                tiers=(
                    EvidenceTier("a", 1, 1, ("Alpha",)),
                    EvidenceTier("b", 1, 1, ("ALPHA",), case_mode="exact"),
                ),
            )
        )


def test_a_lowercase_mode_tier_must_be_configured_in_lowercase() -> None:
    with pytest.raises(ValueError, match="all lowercase"):
        compile_evidence_pack(
            LexicalEvidencePack(
                name="p",
                tiers=(EvidenceTier("a", 1, 1, ("Alpha",), case_mode="lowercase"),),
            )
        )


def test_duplicate_tier_names_are_rejected() -> None:
    with pytest.raises(ValueError, match="duplicate tier name"):
        compile_evidence_pack(
            LexicalEvidencePack(
                name="p",
                tiers=(
                    EvidenceTier("t", 1, 1, ("alpha",)),
                    EvidenceTier("t", 1, 1, ("beta",)),
                ),
            )
        )


def test_band_max_values_groups_by_priority() -> None:
    compiled = compile_evidence_pack(_pack())

    assert band_max_values(list(compiled.tiers)) == (3, 2, 1)
    assert band_max_values([]) == ()


def test_normalize_tokens_lowercases_the_source_tokens() -> None:
    assert normalize_tokens("Market Segments 2024") == ["market", "segments", "2024"]
    assert normalize_tokens("") == []


def test_reason_phrases_cover_each_score_band() -> None:
    assert "decisive evidence" in build_reason(3, ["t"], False, (), "p")
    assert "satisfied weak tier" in build_reason(1, ["t"], False, (), "p")
    assert "below distinct-hit minimum" in build_reason(1, [], True, (), "p")
    assert "exclusion terms only" in build_reason(0, [], False, ("a",), "p")
    assert "no lexical evidence matched" in build_reason(0, [], False, (), "p")
