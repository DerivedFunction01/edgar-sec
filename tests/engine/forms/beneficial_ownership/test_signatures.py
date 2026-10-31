"""Tests for beneficial ownership signature block extraction."""

from edgar_sec.engine.forms.beneficial_ownership.signatures import (
    extract_beneficial_ownership_signature_block,
)


def test_extract_conformed_signature_with_inline_date() -> None:
    """Extract signatory and date from standard conformed signature block."""
    text = """SIGNATURE
After reasonable inquiry, I certify that the info is true.

DATE: September 24, 2020

/s/ Manoj Singh Sole Member of Trust Protection Committee
"""
    block = extract_beneficial_ownership_signature_block(text)
    assert block is not None
    assert len(block.signatories) == 1
    assert block.signatories[0].name == "Manoj Singh"
    assert block.signatories[0].date == "September 24, 2020"


def test_extract_signature_without_conformed_marker() -> None:
    """Extract signatory from plain text signature line when marker is absent."""
    text = """SIGNATURE

Dated: 10/25/2021

Jane Doe
Chief Executive Officer
"""
    block = extract_beneficial_ownership_signature_block(text)
    assert block is not None
    assert len(block.signatories) == 1
    assert block.signatories[0].name == "Jane Doe"
    assert block.signatories[0].date == "10/25/2021"


def test_extract_empty_when_no_signature_region() -> None:
    """Return None when no signature or signatories exist."""
    text = "This is simply narrative text with no signature."
    assert extract_beneficial_ownership_signature_block(text) is None
