"""Unit tests for Unicode whitespace and text normalization."""

from edgar_sec.foundation.text.normalize import (
    collapse_excessive_blank_lines,
    collapse_whitespace,
    fold_smart_quotes,
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


def test_fold_smart_quotes() -> None:
    raw = "\u201cTotal stockholders\u2019 equity,\u201d said \u2018management\u2019"
    assert fold_smart_quotes(raw) == "\"Total stockholders' equity,\" said 'management'"
    # Primes are not quotes in filing text and pass through untouched.
    assert fold_smart_quotes("5\u2032 6\u2033") == "5\u2032 6\u2033"
    assert fold_smart_quotes("") == ""


def test_sanitize_preserves_smart_quotes() -> None:
    # Canonicalization preserves recorded quotes; matchers fold at their own seam.
    raw = "Stonie R. O\u2019Briant"
    assert sanitize_unicode_whitespace(raw) == raw


def test_collapse_whitespace() -> None:
    text = "   Consolidated   Statements  of   Income \t "
    assert collapse_whitespace(text) == "Consolidated Statements of Income"


def test_collapse_excessive_blank_lines() -> None:
    text = "Heading\n\n\n\n\nParagraph text here."
    assert collapse_excessive_blank_lines(text) == "Heading\n\nParagraph text here."
