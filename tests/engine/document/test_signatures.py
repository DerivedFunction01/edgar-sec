"""Tests for shared signature markers and line predicates."""

from edgar_sec.engine.document.signatures import (
    CONFORMED_SIGNATURE_RE,
    RE_CONFORMED_SIGNATURE,
    RE_CONFORMED_SIGNER_NAME,
    RE_POA_SIGNER,
    RE_SIGNATURE_DATE_LINE,
    RE_SIGNATURE_HEADING,
    RE_SIGNATURE_LABEL_LINE,
    is_conformed_signature_line,
    is_signature_label_line,
)


def test_shared_marker_variants_are_consistent() -> None:
    assert RE_CONFORMED_SIGNATURE.match("/s/ Jane Doe")
    assert RE_CONFORMED_SIGNATURE.match("By: /s/ Jane Doe")
    assert is_conformed_signature_line("* By /s/ Jane Doe")
    assert not is_conformed_signature_line("/S/ Jane Doe")
    assert CONFORMED_SIGNATURE_RE.search("[signature]")


def test_shared_signer_and_poa_patterns_match_existing_shapes() -> None:
    assert RE_CONFORMED_SIGNER_NAME.search("/s/ Jane Doe, Date: 1/5/24")
    assert RE_POA_SIGNER.match("*By: Jane Doe")


def test_shared_label_and_heading_patterns_reject_prose() -> None:
    assert is_signature_label_line("  Title: President")
    assert RE_SIGNATURE_LABEL_LINE.match("Signature:")
    assert RE_SIGNATURE_HEADING.search("SIGNATURES")
    assert RE_SIGNATURE_DATE_LINE.match("DATED: January 5, 2024")
    assert not is_signature_label_line("The company signed the agreement")
