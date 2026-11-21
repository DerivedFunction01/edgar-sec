"""Unit tests for domain statutory warning lexical packs."""

from edgar_sec.domain.forms.common.statutory import (
    CERTIFICATION_DECLARATION_PHRASES,
    COMMON_FORM_PHRASE_RULES,
    COMMON_STATUTORY_LEXICAL_PACK,
    FORM_FIELD_PROMPT_TERMS,
    HEADER_LEAK_PHRASES,
    OMB_BURDEN_PHRASES,
    REGULATORY_MASTHEAD_TERMS,
    RULE_10B5_1_PHRASES,
    STATUTORY_CRIMINAL_WARNING_PHRASES,
    STATUTORY_INSTRUCTION_PREFIXES,
    STATUTORY_PAGE_BOILERPLATE,
)
from edgar_sec.foundation.text.automaton import tokenize
from edgar_sec.foundation.text.evidence import (
    EvidenceContext,
    compile_evidence_pack,
    score_tokens,
)


def test_statutory_warning_constants():
    """Verify presence of 18 U.S.C. 1001 phrases."""
    assert len(STATUTORY_CRIMINAL_WARNING_PHRASES) > 0
    assert any("18 u.s.c. 1001" in p for p in STATUTORY_CRIMINAL_WARNING_PHRASES)


def test_common_statutory_lexical_pack_matching():
    """Verify lexical scoring on statutory OMB and collection text."""
    pack = compile_evidence_pack(COMMON_STATUTORY_LEXICAL_PACK)
    ctx = EvidenceContext(min_words=1)
    text = "potential persons who are to respond to the collection of information"
    score = score_tokens(tokenize(text), pack, ctx)
    assert score.score > 0
    assert not score.exclusions


def test_statutory_phrases_and_certifications():
    """Verify 10b5-1, OMB burden, and certification declaration phrases."""
    assert any("rule 10b5-1" in p for p in RULE_10B5_1_PHRASES)
    assert any("burden hours" in p for p in OMB_BURDEN_PHRASES)
    assert any(
        "true, complete and correct" in p for p in CERTIFICATION_DECLARATION_PHRASES
    )
    assert any("see instruction" in p for p in STATUTORY_INSTRUCTION_PREFIXES)
    assert any("schedule 13d" in p for p in REGULATORY_MASTHEAD_TERMS)
    assert any("name of issuer" in p for p in FORM_FIELD_PROMPT_TERMS)


def test_common_form_phrase_rules_cover_existing_vocabularies():
    rule_ids = {rule.rule_id for rule in COMMON_FORM_PHRASE_RULES}

    assert rule_ids == {
        "statutory.certification",
        "statutory.criminal_warning",
        "statutory.header_leak",
        "statutory.omb_burden",
        "statutory.page_boilerplate",
        "statutory.rule_10b5_1",
    }
    phrases = {
        phrase
        for rule in COMMON_FORM_PHRASE_RULES
        for sequence in rule.sequences
        for phrase in sequence
    }
    assert set(STATUTORY_CRIMINAL_WARNING_PHRASES) <= phrases
    assert set(HEADER_LEAK_PHRASES) <= phrases
    assert set(STATUTORY_PAGE_BOILERPLATE) <= phrases
    assert set(CERTIFICATION_DECLARATION_PHRASES) <= phrases
    assert set(OMB_BURDEN_PHRASES) <= phrases
