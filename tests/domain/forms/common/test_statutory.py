"""Unit tests for domain statutory warning lexical packs."""

from edgar_sec.domain.forms.common.statutory import (
    COMMON_STATUTORY_LEXICAL_PACK,
    STATUTORY_CRIMINAL_WARNING_PHRASES,
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
