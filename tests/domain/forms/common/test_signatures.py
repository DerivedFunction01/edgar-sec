"""Unit tests for domain signature models and lexical packs."""

from edgar_sec.domain.forms.common.signatures import (
    COMMON_SIGNATURE_LEXICAL_PACK,
    DelegationKind,
    Signatory,
    SignatureBlock,
)
from edgar_sec.foundation.text.automaton import tokenize
from edgar_sec.foundation.text.evidence import (
    EvidenceContext,
    compile_evidence_pack,
    score_tokens,
)


def test_signatory_instantiation():
    """Verify default and customized signatory properties."""
    sig = Signatory(name="Jane Doe", title="Chief Executive Officer")
    assert sig.name == "Jane Doe"
    assert sig.title == "Chief Executive Officer"
    assert sig.delegation_kind == DelegationKind.DIRECT


def test_signature_block_instantiation():
    """Verify signature block container properties."""
    sig1 = Signatory(name="Jane Doe")
    block = SignatureBlock(signatories=(sig1,), is_conformed=True)
    assert len(block.signatories) == 1
    assert block.is_conformed is True
    assert block.has_notary is False


def test_common_signature_lexical_pack_matching():
    """Verify lexical scoring on conformed signature text."""
    pack = compile_evidence_pack(COMMON_SIGNATURE_LEXICAL_PACK)
    ctx = EvidenceContext(min_words=1)
    text = "by: /s/ john smith authorized signatory"
    score = score_tokens(tokenize(text), pack, ctx)
    assert score.score > 0
    assert not score.exclusions
