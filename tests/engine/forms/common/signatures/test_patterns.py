"""Unit tests for compiled signature lexical patterns."""

from edgar_sec.engine.document.signatures import CONFORMED_SIGNATURE_RE
from edgar_sec.engine.forms.common.signatures.patterns import (
    NOTARY_JURAT_RE,
    OFFICER_TITLE_RE,
    POA_AUTH_RE,
    SIGNATORY_ROLE_RE,
)


def test_signature_regexes():
    """Verify compiled signature, role, and notary regexes."""
    assert bool(CONFORMED_SIGNATURE_RE.search("/s/ Jane"))
    assert bool(NOTARY_JURAT_RE.search("Subscribed and sworn before me"))
    assert bool(OFFICER_TITLE_RE.search("Vice President"))
    assert bool(SIGNATORY_ROLE_RE.search("Managing Member"))
    assert bool(POA_AUTH_RE.search("Know all by these presents"))
