"""Tests for Form 144 lexical evidence definitions."""

from edgar_sec.domain.forms.families.form144.evidence import (
    FORM144_BOX_1_2_LEXICAL_PACK,
    FORM144_INSTRUCTION_PHRASE_RULE,
    FORM144_INSTRUCTION_VETO_PHRASES,
    FORM144_TABLE_I_LEXICAL_PACK,
    FORM144_TABLE_II_LEXICAL_PACK,
)
from edgar_sec.foundation.text.automaton import tokenize
from edgar_sec.foundation.text.evidence import (
    EvidenceContext,
    compile_evidence_pack,
    score_tokens,
)


def test_box_1_2_evidence_scoring():
    sample_text = "1 (a) name of issuer (b) irs ident. no. (c) s.e.c. file no. 2 (a) name of person for whose account"
    tokens = tokenize(sample_text)
    compiled = compile_evidence_pack(FORM144_BOX_1_2_LEXICAL_PACK)
    scored = score_tokens(tokens, compiled, EvidenceContext(min_words=1))
    assert scored.score >= 3
    assert scored.classification == "matched"


def test_table_i_and_ii_evidence():
    compiled_t1 = compile_evidence_pack(FORM144_TABLE_I_LEXICAL_PACK)
    t1_tokens = tokenize(
        "table i - securities to be sold date you acquired amount of securities acquired"
    )
    t1_scored = score_tokens(t1_tokens, compiled_t1, EvidenceContext(min_words=1))
    assert t1_scored.score >= 3
    assert t1_scored.classification == "matched"

    compiled_t2 = compile_evidence_pack(FORM144_TABLE_II_LEXICAL_PACK)
    t2_tokens = tokenize(
        "table ii - securities sold during the past 3 months gross proceeds"
    )
    t2_scored = score_tokens(t2_tokens, compiled_t2, EvidenceContext(min_words=1))
    assert t2_scored.score >= 3
    assert t2_scored.classification == "matched"


def test_instruction_phrase_rule_is_family_scoped_and_source_neutral():
    phrases = {
        phrase
        for sequence in FORM144_INSTRUCTION_PHRASE_RULE.sequences
        for phrase in sequence
    }

    assert FORM144_INSTRUCTION_PHRASE_RULE.rule_id == "form144.instruction_veto"
    assert FORM144_INSTRUCTION_PHRASE_RULE.family_ids == frozenset({"144"})
    assert phrases == set(FORM144_INSTRUCTION_VETO_PHRASES)
