"""Unit tests for engine common entities regexes."""

from edgar_sec.engine.forms.common.entities import (
    CLEAN_TEMPLATE_RE,
    IRS_RE,
    STATE_ZIP_RE,
    STREET_ANCHOR_RE,
    TICKER_PAREN_RE,
)


def test_state_zip_and_irs_matching():
    """Verify state/zip and IRS tax ID extraction."""
    assert bool(STATE_ZIP_RE.search("New York, NY 10001"))
    assert bool(IRS_RE.search("12-3456789"))
    assert bool(IRS_RE.search("123456789"))


def test_clean_template_and_ticker():
    """Verify template artifact stripping and ticker regex."""
    assert bool(CLEAN_TEMPLATE_RE.search("(Last)"))
    assert bool(STREET_ANCHOR_RE.search("123 Main Street"))
    match = TICKER_PAREN_RE.search("(NASDAQ: AAPL)")
    assert match is not None
    assert match.group(1) == "AAPL"
