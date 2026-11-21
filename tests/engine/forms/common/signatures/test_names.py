"""Unit tests for signature name cleaning and validation."""

from edgar_sec.domain.forms.common.signatures import DelegationKind
from edgar_sec.engine.forms.common.signatures.names import (
    clean_signature_name,
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
    repeated = "James P. Ryan James P. Ryan"
    assert clean_signature_name(repeated) == "James P. Ryan"


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


def test_is_valid_signature_name():
    """Verify acceptance of person names and rejection of boilerplate."""
    assert is_valid_signature_name("John Doe") is True
    assert is_valid_signature_name("Table I") is False
    assert is_valid_signature_name("TABLE II") is False
    assert is_valid_signature_name("Table 1") is False
    assert is_valid_signature_name("Table 2") is False


def test_clean_name_drops_title_segment_after_ampersand() -> None:
    from edgar_sec.engine.forms.common.signatures.names import (
        extract_clean_signatory_name,
        is_valid_signature_name,
    )

    assert (
        extract_clean_signatory_name("Christian S. Schade & Chief Financial Officer")
        == "Christian S. Schade"
    )
    assert (
        extract_clean_signatory_name("Dan Goldstein & Chief Executive Officer")
        == "Dan Goldstein"
    )
    assert extract_clean_signatory_name("Chief Financial Officer") is None
    assert not is_valid_signature_name("Attorney-in-Fact for")


def test_extract_clean_signatory_name_strips_surrounding_quotes() -> None:
    from edgar_sec.engine.forms.common.signatures.names import (
        extract_clean_signatory_name,
    )

    assert extract_clean_signatory_name("“Peter Evensen”") == "Peter Evensen"
    assert extract_clean_signatory_name('"Peter Evensen"') == "Peter Evensen"
