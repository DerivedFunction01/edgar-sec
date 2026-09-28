"""Unit tests for Unicode whitespace and text normalization."""

from edgar_sec.foundation.text.normalize import (
    collapse_excessive_blank_lines,
    collapse_whitespace,
    sanitize_unicode_whitespace,
)


def test_sanitize_unicode_whitespace() -> None:
    # Non-breaking space \u00a0, narrow no-break \u202f, thin space \u2009
    raw = "Item\u00a01A.\u202fRisk\u2009Factors"
    sanitized = sanitize_unicode_whitespace(raw)
    assert sanitized == "Item 1A. Risk Factors"

    # Zero-width spaces and markers
    with_zw = "Securities\u200b\u200c\u200dExchange"
    assert sanitize_unicode_whitespace(with_zw) == "SecuritiesExchange"


def test_collapse_whitespace() -> None:
    text = "   Consolidated   Statements  of   Income \t "
    assert collapse_whitespace(text) == "Consolidated Statements of Income"


def test_collapse_excessive_blank_lines() -> None:
    text = "Heading\n\n\n\n\nParagraph text here."
    assert collapse_excessive_blank_lines(text) == "Heading\n\nParagraph text here."
