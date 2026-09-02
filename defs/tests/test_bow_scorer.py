"""Contract tests for the shared lexical evidence scorer."""

from __future__ import annotations

import pytest

from defs.sec_forms.forms.annual.evidence import ANNUAL_BODY_LEXICAL_PACK
from defs.sec_forms.forms.common import derive_lexical_pack
from defs.text.bow import (
    BowScore,
    CaseMode,
    CompiledEvidencePack,
    EvidenceContext,
    EvidenceTier,
    LexicalEvidencePack,
    compile_evidence_pack,
    normalize_tokens,
    score_tokens,
    score_unit,
    tokenize,
)


def _pack(
    tiers: tuple[EvidenceTier, ...], exclusions: tuple[str, ...] = ()
) -> LexicalEvidencePack:
    return LexicalEvidencePack(
        name="test_pack", tiers=tiers, exclusion_terms=exclusions
    )


def _loose() -> EvidenceContext:
    return EvidenceContext(min_words=2)


# --- Score semantics ---------------------------------------------------------


def test_decisive_phrase_returns_score_three() -> None:
    text = (
        "The company sells products to customers through its market segments "
        "worldwide and maintains long-term agreements with suppliers."
    )
    result = score_unit(text, ANNUAL_BODY_LEXICAL_PACK)
    assert result.score == 3
    assert result.classification == "matched"
    assert result.satisfied_tiers == ("body_phrase",)
    assert result.short_circuited is True
    assert result.evaluated_tiers == ("body_phrase",)


def test_two_distinct_strong_unigrams_score_two() -> None:
    text = (
        "The company was founded in 1985 and serves customers worldwide "
        "through a growing portfolio of regional operations."
    )
    result = score_unit(text, ANNUAL_BODY_LEXICAL_PACK)
    assert result.score == 2
    assert result.classification == "matched"
    assert result.satisfied_tiers == ("body_strong",)
    assert result.short_circuited is True


def test_single_strong_unigram_is_intermediate() -> None:
    text = "The company was founded in 1985 by two engineers in a small garage."
    result = score_unit(text, ANNUAL_BODY_LEXICAL_PACK)
    assert result.score == 1
    assert result.classification == "ambiguous"
    assert result.satisfied_tiers == ()


def test_two_distinct_weak_unigrams_score_one() -> None:
    text = "The company provides legal services and develops new products each year."
    result = score_unit(text, ANNUAL_BODY_LEXICAL_PACK)
    assert result.score == 1
    assert result.classification == "ambiguous"
    assert result.satisfied_tiers == ("body_weak",)


def test_one_repeated_weak_term_scores_zero() -> None:
    text = "provides provides provides and nothing else of note appears here"
    result = score_unit(text, ANNUAL_BODY_LEXICAL_PACK)
    assert result.score == 0
    assert result.classification == "no_match"
    assert result.satisfied_tiers == ()


def test_strong_plus_weak_evidence_stays_intermediate() -> None:
    text = "The company was founded in 1985 and provides services to clients."
    result = score_unit(text, ANNUAL_BODY_LEXICAL_PACK)
    assert result.score == 1
    assert result.classification == "ambiguous"
    assert result.satisfied_tiers == ("body_weak",)


def test_exclusion_only_text_scores_zero() -> None:
    text = (
        "Pursuant to the requirements herein, the registrant has duly caused "
        "this report to be signed on its behalf by the undersigned."
    )
    result = score_unit(text, ANNUAL_BODY_LEXICAL_PACK)
    assert result.score == 0
    assert result.classification == "no_match"
    assert len(result.exclusions) >= 3
    assert "exclusion terms" in result.reason


def test_exclusions_do_not_veto_body_evidence() -> None:
    text = (
        "Pursuant to the plan, the company was founded in 1985 and serves "
        "customers worldwide through its regional operations."
    )
    result = score_unit(text, ANNUAL_BODY_LEXICAL_PACK)
    assert result.score == 2
    assert "pursuant" in result.exclusions


# --- Matching semantics -------------------------------------------------------


def test_phrase_matches_hyphenated_and_spaced_forms() -> None:
    pack = _pack(
        (
            EvidenceTier(
                name="phrase",
                priority=30,
                value=3,
                terms=("interest rate",),
                match_kind="ngram",
                min_distinct_hits=1,
            ),
        )
    )
    context = EvidenceContext(min_words=2)
    for text in (
        "The interest rate declined",
        "The interest-rate declined",
        "The interest\u2013rate declined",
        "The INTEREST rate declined",
    ):
        result = score_unit(text, pack, context)
        assert result.score == 3, text


def test_fold_mode_preserves_existing_case_insensitive_behavior() -> None:
    pack = _pack(
        (
            EvidenceTier(
                name="folded",
                priority=20,
                value=2,
                terms=("facilities", "customers"),
                match_kind="unigram",
                min_distinct_hits=2,
            ),
        )
    )
    text = "The company has FACILITIES serving CUSTOMERS throughout the region."
    result = score_unit(text, pack)
    assert result.score == 2
    assert {hit.case_mode for hit in result.hits} == {CaseMode.FOLD.value}


def test_exact_case_mode_only_matches_configured_surface_case() -> None:
    pack = _pack(
        (
            EvidenceTier(
                name="us_exact",
                priority=20,
                value=2,
                terms=("US",),
                match_kind="unigram",
                min_distinct_hits=1,
                case_mode=CaseMode.EXACT,
            ),
        )
    )
    matching = score_unit(
        "The company operates across the US market and serves customers worldwide.\n",
        pack,
    )
    assert matching.score == 2
    assert matching.hits[0].term == "US"
    assert matching.hits[0].case_mode == CaseMode.EXACT.value

    for source in ("Us", "us"):
        result = score_unit(
            f"The company operates across the {source} market and serves customers worldwide.\n",
            pack,
        )
        assert result.score == 0, source
        assert result.hits == ()


def test_lowercase_case_mode_rejects_title_case_month() -> None:
    pack = _pack(
        (
            EvidenceTier(
                name="may_lowercase",
                priority=20,
                value=2,
                terms=("may",),
                match_kind="unigram",
                min_distinct_hits=1,
                case_mode=CaseMode.LOWERCASE,
            ),
        )
    )
    lowercase = score_unit(
        "The company may operate facilities throughout the region this year.",
        pack,
    )
    assert lowercase.score == 2
    assert lowercase.hits[0].case_mode == CaseMode.LOWERCASE.value

    title_case = score_unit(
        "May operate facilities throughout the region during the reporting year.",
        pack,
    )
    assert title_case.score == 0
    assert title_case.hits == ()


def test_case_sensitive_and_folded_bags_same_priority_are_alternatives() -> None:
    pack = _pack(
        (
            EvidenceTier(
                name="exact_us",
                priority=20,
                value=2,
                terms=("US",),
                match_kind="unigram",
                min_distinct_hits=1,
                case_mode=CaseMode.EXACT,
            ),
            EvidenceTier(
                name="folded_facilities",
                priority=20,
                value=2,
                terms=("facilities",),
                match_kind="unigram",
                min_distinct_hits=1,
            ),
        )
    )
    result = score_unit(
        "The company operates in the US market and maintains facilities worldwide.",
        pack,
    )
    assert result.score == 2
    assert result.satisfied_tiers == ("exact_us",)
    assert result.short_circuited is True
    assert result.evaluated_tiers == ("exact_us", "folded_facilities")
    assert [hit.term for hit in result.hits] == ["US"]


def test_same_priority_bags_do_not_sum_distinct_hits() -> None:
    pack = _pack(
        (
            EvidenceTier(
                name="exact_us",
                priority=20,
                value=2,
                terms=("US",),
                match_kind="unigram",
                min_distinct_hits=2,
                case_mode=CaseMode.EXACT,
            ),
            EvidenceTier(
                name="folded_facilities",
                priority=20,
                value=2,
                terms=("facilities",),
                match_kind="unigram",
                min_distinct_hits=2,
            ),
        )
    )
    result = score_unit(
        "The company operates in the US market and maintains facilities worldwide.",
        pack,
    )
    assert result.score == 0
    assert result.satisfied_tiers == ()


def test_same_folded_term_cannot_use_multiple_case_modes() -> None:
    pack = _pack(
        (
            EvidenceTier(
                name="exact_us",
                priority=20,
                value=2,
                terms=("US",),
                case_mode=CaseMode.EXACT,
            ),
            EvidenceTier(
                name="folded_us",
                priority=10,
                value=1,
                terms=("us",),
                case_mode=CaseMode.FOLD,
            ),
        )
    )
    with pytest.raises(ValueError, match="multiple case modes"):
        compile_evidence_pack(pack)


def test_three_word_phrase_matches() -> None:
    pack = _pack(
        (
            EvidenceTier(
                name="phrase",
                priority=30,
                value=3,
                terms=("share based compensation",),
                match_kind="ngram",
                min_distinct_hits=1,
            ),
        )
    )
    context = EvidenceContext(min_words=2)
    for text in ("Share-based compensation expense", "share based compensation cost"):
        assert score_unit(text, pack, context).score == 3


def test_phrase_matching_is_token_boundary_safe() -> None:
    pack = _pack(
        (
            EvidenceTier(
                name="phrase",
                priority=30,
                value=3,
                terms=("labor union",),
                match_kind="ngram",
                min_distinct_hits=1,
            ),
        )
    )
    text = "The labor unions negotiated a new contract with several employers."
    result = score_unit(text, pack)
    assert result.score == 0
    assert result.hits == ()


def test_unigram_matching_is_token_boundary_safe() -> None:
    pack = _pack(
        (
            EvidenceTier(
                name="strong",
                priority=20,
                value=2,
                terms=("form",),
                match_kind="unigram",
                min_distinct_hits=1,
            ),
        )
    )
    text = "The formal agreement was signed by both parties last week."
    assert score_unit(text, pack).score == 0


def test_hits_record_distinct_terms_and_counts() -> None:
    text = (
        "The company was founded in 1985 and serves customers worldwide; "
        "customers worldwide rely on the products every day."
    )
    result = score_unit(text, ANNUAL_BODY_LEXICAL_PACK)
    terms = {hit.term: hit for hit in result.hits if hit.tier == "body_strong"}
    assert terms["customers"].count == 2
    assert terms["customers"].positions == (8, 10)
    assert terms["worldwide"].count == 2
    assert len([hit for hit in result.hits if hit.tier == "body_strong"]) >= 2


def test_hits_are_deterministically_ordered() -> None:
    text = (
        "The company operates facilities and serves customers and suppliers "
        "worldwide through its segments."
    )
    result = score_unit(text, ANNUAL_BODY_LEXICAL_PACK)
    strong_terms = [hit.term for hit in result.hits if hit.tier == "body_strong"]
    assert strong_terms == sorted(strong_terms)


def test_short_circuit_skips_lower_tier_evaluation() -> None:
    text = (
        "The company sells products through its market segments worldwide "
        "with employees in many locations."
    )
    result = score_unit(text, ANNUAL_BODY_LEXICAL_PACK)
    assert result.score == 3
    assert result.evaluated_tiers == ("body_phrase",)
    assert result.short_circuited is True


def test_evaluated_tiers_record_search_order() -> None:
    text = "The company was founded in 1985 and serves customers worldwide."
    result = score_unit(text, ANNUAL_BODY_LEXICAL_PACK)
    assert result.evaluated_tiers == ("body_phrase", "body_strong")


def test_prefix_vocab_is_diagnostic_only() -> None:
    text = "The company was founded in 1985 and serves customers worldwide."
    partial = score_unit(
        text,
        ANNUAL_BODY_LEXICAL_PACK,
        EvidenceContext(prefix_vocab=frozenset({"the", "company", "was", "in"})),
    )
    full = score_unit(
        text,
        ANNUAL_BODY_LEXICAL_PACK,
        EvidenceContext(prefix_vocab=frozenset(normalize_tokens(text))),
    )
    assert partial.score == full.score == 2
    assert partial.novel_count > 0
    assert full.novel_count == 0


# --- Compilation and reuse ----------------------------------------------------


def test_compiled_pack_is_cached_by_value() -> None:
    assert compile_evidence_pack(ANNUAL_BODY_LEXICAL_PACK) is compile_evidence_pack(
        ANNUAL_BODY_LEXICAL_PACK
    )


def test_compiled_pack_reuse_matches_fresh_compile() -> None:
    text = "The company was founded in 1985 and serves customers worldwide."
    compiled = compile_evidence_pack(ANNUAL_BODY_LEXICAL_PACK)
    tokens = tokenize(text)
    assert score_tokens(tokens, compiled) == score_unit(text, ANNUAL_BODY_LEXICAL_PACK)


def test_empty_pack_scores_zero() -> None:
    result = score_unit(
        "An ordinary paragraph with several words in it already.",
        LexicalEvidencePack(name="empty"),
    )
    assert result.score == 0
    assert result.classification == "no_match"
    assert "no tiers" in result.reason


def test_score_unit_accepts_compiled_pack() -> None:
    text = "The company sells products through its market segments worldwide."
    compiled = compile_evidence_pack(ANNUAL_BODY_LEXICAL_PACK)
    assert isinstance(compiled, CompiledEvidencePack)
    assert score_unit(text, compiled).score == 3


def test_malformed_tiers_raise_at_compile() -> None:
    with pytest.raises(ValueError):
        EvidenceTier(name="bad", priority=1, value=4, terms=("x",))
    with pytest.raises(ValueError):
        EvidenceTier(
            name="bad", priority=1, value=1, terms=("x",), match_kind="trigram"
        )
    with pytest.raises(ValueError):
        EvidenceTier(name="bad", priority=1, value=1, terms=("x",), min_distinct_hits=0)
    with pytest.raises(ValueError):
        compile_evidence_pack(
            _pack(
                (
                    EvidenceTier(
                        name="strong", priority=1, value=2, terms=("two words",)
                    ),
                )
            )
        )
    with pytest.raises(ValueError):
        compile_evidence_pack(
            _pack(
                (
                    EvidenceTier(
                        name="phrase",
                        priority=30,
                        value=3,
                        terms=("one",),
                        match_kind="ngram",
                    ),
                )
            )
        )
    with pytest.raises(ValueError):
        compile_evidence_pack(
            _pack(
                (
                    EvidenceTier(name="a", priority=10, value=1, terms=("x",)),
                    EvidenceTier(name="a", priority=20, value=2, terms=("y",)),
                )
            )
        )
    with pytest.raises(ValueError):
        compile_evidence_pack(
            _pack((EvidenceTier(name="empty", priority=10, value=1, terms=()),))
        )


def test_derive_lexical_pack_from_legacy_fields() -> None:
    pack = derive_lexical_pack(
        body_ngrams=("cloud computing", "business"),
        body_verbs=("provides", "operates"),
        body_terms=("company", "facilities"),
        cover_terms=("pursuant",),
    )
    compiled = compile_evidence_pack(pack)
    assert [tier.name for tier in compiled.tiers] == [
        "body_phrase",
        "body_strong",
        "body_weak",
    ]
    assert compiled.exclusions == frozenset({"pursuant"})

    phrase_result = score_unit(
        "The company provides cloud computing services to enterprise customers.",
        pack,
    )
    assert phrase_result.score == 3
    strong_result = score_unit(
        "The company operates facilities and its business grew quickly.", pack
    )
    assert strong_result.score == 2


# --- Result contract ----------------------------------------------------------


def test_bow_score_is_frozen() -> None:
    result = BowScore(score=2, classification="matched", confidence=0.9)
    assert result.score == 2
    with pytest.raises(AttributeError):
        result.score = 1  # type: ignore[misc]


def test_ineligible_context_scores_zero_with_reason() -> None:
    text = "The company sells products through its market segments worldwide."
    result = score_unit(
        text,
        ANNUAL_BODY_LEXICAL_PACK,
        EvidenceContext(eligible=False, exclusion_reason="unit is a table"),
    )
    assert result.score == 0
    assert result.reason == "unit is a table"


def test_too_few_words_scores_zero() -> None:
    result = score_unit("The company operates.", ANNUAL_BODY_LEXICAL_PACK)
    assert result.score == 0
    assert "below minimum" in result.reason


def test_empty_text_scores_zero() -> None:
    assert score_unit("", ANNUAL_BODY_LEXICAL_PACK).score == 0


def test_score_range_and_classification_are_stable() -> None:
    text = (
        "The company was founded in 1985, operates manufacturing facilities, "
        "and serves customers worldwide."
    )
    result = score_unit(text, ANNUAL_BODY_LEXICAL_PACK)
    assert result.score in (0, 1, 2, 3)
    assert result.classification in ("no_match", "ambiguous", "matched")


# --- Later-phase domain packs reuse the same engine ----------------------------


def test_labor_pack_reuses_engine() -> None:
    labor = _pack(
        (
            EvidenceTier(
                name="phrase",
                priority=30,
                value=3,
                terms=("collective bargaining agreement",),
                match_kind="ngram",
                min_distinct_hits=1,
            ),
            EvidenceTier(
                name="strong",
                priority=20,
                value=2,
                terms=("union", "unionized", "grievance", "workforce"),
                match_kind="unigram",
                min_distinct_hits=2,
            ),
        )
    )
    decisive = score_unit(
        "The parties negotiated a collective bargaining agreement last year.",
        labor,
    )
    assert decisive.score == 3
    strong = score_unit(
        "The workforce is unionized and the union filed a grievance last month.",
        labor,
    )
    assert strong.score == 2


def test_derivative_pack_reuses_engine() -> None:
    derivative = _pack(
        (
            EvidenceTier(
                name="phrase",
                priority=30,
                value=3,
                terms=("interest rate swap", "foreign exchange forward"),
                match_kind="ngram",
                min_distinct_hits=1,
            ),
            EvidenceTier(
                name="strong",
                priority=20,
                value=2,
                terms=("swap", "hedge", "notional", "derivative"),
                match_kind="unigram",
                min_distinct_hits=2,
            ),
        )
    )
    assert (
        score_unit(
            "The company entered into an interest-rate swap during the period.",
            derivative,
        ).score
        == 3
    )
    assert (
        score_unit(
            "The derivative positions hedge notional exposure to the swap book.",
            derivative,
        ).score
        == 2
    )


def test_stock_compensation_pack_reuses_engine() -> None:
    compensation = _pack(
        (
            EvidenceTier(
                name="phrase",
                priority=30,
                value=3,
                terms=("share based compensation", "restricted stock"),
                match_kind="ngram",
                min_distinct_hits=1,
            ),
            EvidenceTier(
                name="strong",
                priority=20,
                value=2,
                terms=("vesting", "option", "award", "grant"),
                match_kind="unigram",
                min_distinct_hits=2,
            ),
        )
    )
    assert (
        score_unit(
            "The company records share-based compensation expense for each award.",
            compensation,
        ).score
        == 3
    )
    assert (
        score_unit(
            "Each option grant vests over four years for every award granted.",
            compensation,
        ).score
        == 2
    )
