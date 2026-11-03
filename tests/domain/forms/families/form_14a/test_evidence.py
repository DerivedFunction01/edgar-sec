from __future__ import annotations

from edgar_sec.domain.forms.families.form_14a.evidence import (
    FORM_14A_BODY_LEXICAL_PACK,
    FORM_14A_BODY_PHRASES,
    FORM_14A_BODY_STRONG_TERMS,
    FORM_14A_BODY_WEAK_TERMS,
    FORM_14A_COVER_EXCLUSION_TERMS,
    Form14AEvidence,
)


def test_form_14a_evidence_terms() -> None:
    assert len(FORM_14A_BODY_PHRASES) > 0
    assert len(FORM_14A_BODY_STRONG_TERMS) > 0
    assert len(FORM_14A_BODY_WEAK_TERMS) > 0
    assert "board of directors" in FORM_14A_BODY_PHRASES
    assert "election of directors" in FORM_14A_BODY_PHRASES
    assert "stockholders" in FORM_14A_BODY_STRONG_TERMS
    assert "ratify" in FORM_14A_BODY_WEAK_TERMS
    assert "charter" in FORM_14A_COVER_EXCLUSION_TERMS


def test_form_14a_evidence_model() -> None:
    evidence = Form14AEvidence()
    assert evidence.body_ngrams == FORM_14A_BODY_PHRASES
    assert evidence.body_verbs == FORM_14A_BODY_WEAK_TERMS
    assert evidence.body_terms == FORM_14A_BODY_STRONG_TERMS
    assert evidence.cover_terms == FORM_14A_COVER_EXCLUSION_TERMS
    assert evidence.body_lexical is FORM_14A_BODY_LEXICAL_PACK


def test_form_14a_lexical_pack_declares_all_four_tiers_in_order() -> None:
    assert FORM_14A_BODY_LEXICAL_PACK.name == "form_14a_body_start"
    tiers = FORM_14A_BODY_LEXICAL_PACK.tiers
    assert tuple(tier.name for tier in tiers) == (
        "body_phrase",
        "body_strong",
        "body_forward",
        "body_weak",
    )
    assert tiers[0].value == 3 and tiers[0].min_distinct_hits == 1
    assert tiers[1].value == 2 and tiers[1].min_distinct_hits == 2
