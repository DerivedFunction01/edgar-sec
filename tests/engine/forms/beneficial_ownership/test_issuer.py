"""Tests for issuer header metadata extraction."""

from __future__ import annotations

from edgar_sec.engine.forms.beneficial_ownership.issuer import extract_issuer_metadata

_SAMPLE_HEADER = """
Name of Issuer: Stanley Furniture Company, Inc.
Title of Class of Securities: Common Stock, Par Value $0.02 Per Share
CUSIP Number: 854305208
Name of Person Authorized to Receive Notices and Communications: Justyn R. Putnam
Date of Event Which Requires Filing of This Statement: January 30, 2017
"""


def test_extract_issuer_metadata_parses_fields() -> None:
    meta = extract_issuer_metadata(_SAMPLE_HEADER)
    assert meta.issuer_name == "Stanley Furniture Company, Inc."
    assert meta.security_class == "Common Stock, Par Value $0.02 Per Share"
    assert meta.cusip == "854305208"
    assert meta.event_date == "January 30, 2017"
    assert meta.notice_contact == "Justyn R. Putnam"
