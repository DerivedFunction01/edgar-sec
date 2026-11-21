from __future__ import annotations

from edgar_sec.domain.forms.families.form_11k.evidence import (
    FORM_11K_BODY_LEXICAL_PACK,
    FORM_11K_BODY_PHRASES,
    FORM_11K_BODY_STRONG_TERMS,
    FORM_11K_BODY_WEAK_TERMS,
    Form11KEvidence,
)


def test_form_11k_evidence_terms() -> None:
    assert len(FORM_11K_BODY_PHRASES) > 0
    assert len(FORM_11K_BODY_STRONG_TERMS) > 0
    assert len(FORM_11K_BODY_WEAK_TERMS) > 0
    assert "statements of net assets available for benefits" in FORM_11K_BODY_PHRASES
    assert "financial" in FORM_11K_BODY_STRONG_TERMS
    assert "audited" in FORM_11K_BODY_WEAK_TERMS


def test_form_11k_evidence_model() -> None:
    evidence = Form11KEvidence()
    assert evidence.body_ngrams == FORM_11K_BODY_PHRASES
    assert evidence.body_verbs == FORM_11K_BODY_WEAK_TERMS
    assert evidence.body_terms == FORM_11K_BODY_STRONG_TERMS
    assert evidence.body_lexical is FORM_11K_BODY_LEXICAL_PACK


def test_form_11k_lexical_pack_declares_tiers_in_order() -> None:
    assert FORM_11K_BODY_LEXICAL_PACK.name == "form_11k_body_start"
    tiers = FORM_11K_BODY_LEXICAL_PACK.tiers
    assert tuple(tier.name for tier in tiers) == (
        "body_phrase",
        "body_strong",
        "body_weak",
    )
    assert tiers[0].value == 3 and tiers[0].min_distinct_hits == 1
    assert tiers[1].value == 2 and tiers[1].min_distinct_hits == 2
