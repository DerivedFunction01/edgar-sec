"""Unit tests for engine signature parsing utilities."""

from edgar_sec.domain.forms.common.signatures import DelegationKind
from edgar_sec.engine.forms.common.signatures import (
    CONFORMED_SIGNATURE_RE,
    NOTARY_JURAT_RE,
    OFFICER_TITLE_RE,
    POA_AUTH_RE,
    SIGNATORY_ROLE_RE,
    clean_signature_name,
    extract_signature_block,
    extract_signature_candidate,
    is_valid_signature_name,
    parse_conformed_signature,
    resolve_delegated_signer,
)


def test_clean_signature_name():
    """Verify stripping of dashes, labels, and markup."""
    raw = "___ /s/ Jane Doe ___"
    assert clean_signature_name(raw) == "Jane Doe"
    raw_by = "By: John Smith"
    assert clean_signature_name(raw_by) == "John Smith"


def test_parse_conformed_signature():
    """Verify detection of /s/ markup."""
    text_conf = "/s/ Alice Johnson"
    name, is_conf = parse_conformed_signature(text_conf)
    assert name == "Alice Johnson"
    assert is_conf is True

    text_plain = "Bob Williams"
    name2, is_conf2 = parse_conformed_signature(text_plain)
    assert name2 == "Bob Williams"
    assert is_conf2 is False


def test_resolve_delegated_signer():
    """Verify detection of power of attorney delegations."""
    poa_text = "Jane Doe, Attorney-in-Fact"
    name, kind, agent = resolve_delegated_signer(poa_text)
    assert kind == DelegationKind.POWER_OF_ATTORNEY
    assert agent == "Jane Doe"


def test_extract_signature_candidate():
    """Verify signature candidate name and date parsing."""
    text = "/s/ Robert Taylor\nNovember 15, 2023\n"
    name, date = extract_signature_candidate(text)
    assert name == "Robert Taylor"
    assert date == "November 15, 2023"


def test_signature_regexes():
    """Verify compiled signature, role, and notary regexes."""
    assert bool(CONFORMED_SIGNATURE_RE.search("/s/ Jane"))
    assert bool(NOTARY_JURAT_RE.search("Subscribed and sworn before me"))
    assert bool(OFFICER_TITLE_RE.search("Vice President"))
    assert bool(SIGNATORY_ROLE_RE.search("Managing Member"))
    assert bool(POA_AUTH_RE.search("Know all by these presents"))


def test_extract_signature_block():
    """Verify structured signature block extraction."""
    block_text = "/s/ John Doe\nBy: Jane Smith, Attorney-in-Fact\n"
    block = extract_signature_block(block_text)
    assert block is not None
    assert block.is_conformed is True
    assert len(block.signatories) >= 1


def test_is_valid_signature_name():
    """Verify acceptance of person names and rejection of boilerplate."""
    assert is_valid_signature_name("John Doe") is True
    assert is_valid_signature_name("Table I") is False
    assert is_valid_signature_name("TABLE II") is False
    assert is_valid_signature_name("Table 1") is False
    assert is_valid_signature_name("Table 2") is False
