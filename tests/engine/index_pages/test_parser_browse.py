"""Tests for browse-edgar series page parsing over captured fixtures."""

from __future__ import annotations

import pytest

from edgar_sec.domain.browse_urls import browse_company_url, browse_series_url
from edgar_sec.engine.index_pages.parser_browse import (
    PARSER_FINGERPRINT,
    BrowseClassRow,
    BrowsePageInput,
    BrowseParseFailure,
    BrowseParseOutcome,
    BrowseSeriesRow,
    ParsedBrowseSeriesPage,
    UnrecognizedBrowsePage,
    parse_browse_series_page,
)
from tests.support import fixture_path


def _parse(cik: str, fixture: str, url: str) -> BrowseParseOutcome:
    return parse_browse_series_page(
        BrowsePageInput(cik, url, fixture_path(fixture).read_bytes())
    )


def _parsed(cik: str) -> ParsedBrowseSeriesPage:
    outcome = _parse(cik, f"browse_edgar_series_{cik}.html", browse_series_url(cik))
    assert isinstance(outcome, ParsedBrowseSeriesPage)
    return outcome


def test_single_series_page_parses_exactly() -> None:
    page = _parsed("0000002663")

    assert page.cik == "0000002663"
    assert page.registrant_name == "VOYA GOVERNMENT MONEY MARKET PORTFOLIO"
    assert page.declared_item_count == 5
    assert page.series == (
        BrowseSeriesRow("S000008702", "Voya Government Money Market Portfolio"),
    )
    assert page.classes == (
        BrowseClassRow("S000008702", "C000023718", "Class I", "IVMXX"),
        BrowseClassRow("S000008702", "C000028786", "Class S", None),
        BrowseClassRow("S000008702", "C000074895", "Class S2", None),
        BrowseClassRow("S000008702", "C000076529", "Class ADV", None),
    )
    assert page.diagnostics.items == ()


def test_multi_series_page_parses_to_the_probed_set() -> None:
    page = _parsed("0000003521")

    assert page.registrant_name == "ALGER FUNDS"
    assert page.declared_item_count == 106
    assert len(page.series) == 19
    assert len(page.classes) == 87
    assert sum(1 for row in page.classes if row.symbol is None) == 14
    assert page.series[0] == BrowseSeriesRow(
        "S000009159", "Alger International Opportunities Fund"
    )
    assert page.classes[0] == BrowseClassRow(
        "S000009159",
        "C000024900",
        "Alger International Opportunities Fund Class A",
        "ALGAX",
    )
    series_ids = {row.series_id for row in page.series}
    assert {row.series_id for row in page.classes} <= series_ids


def test_large_trust_page_parses_without_pagination() -> None:
    page = _parsed("0001100663")

    assert page.declared_item_count == 1124
    assert len(page.series) == 562
    assert len(page.classes) == 562
    assert sum(1 for row in page.classes if row.symbol is None) == 26
    names = {row.series_name for row in page.series}
    assert "iShares S&P 100 ETF" in names


def test_company_page_is_unrecognized() -> None:
    outcome = _parse(
        "0000003521",
        "browse_edgar_company_0000003521.html",
        browse_company_url(3521),
    )

    assert isinstance(outcome, UnrecognizedBrowsePage)
    assert [d.code for d in outcome.diagnostics.items] == ["missing_series_heading"]


def test_cik_mismatch_is_a_failure() -> None:
    outcome = _parse(
        "0000003521",
        "browse_edgar_series_0000002663.html",
        browse_series_url(3521),
    )

    assert isinstance(outcome, BrowseParseFailure)
    assert [d.code for d in outcome.diagnostics.items] == ["cik_mismatch"]


def test_drifted_items_header_fails_the_page() -> None:
    raw = fixture_path("browse_edgar_series_0000002663.html").read_bytes()
    drifted = raw.replace(b"Items 1 - 5", b"Items 1 - 9")
    assert drifted != raw

    outcome = parse_browse_series_page(
        BrowsePageInput("0000002663", browse_series_url(2663), drifted)
    )

    assert isinstance(outcome, BrowseParseFailure)
    assert "item_count_mismatch" in [d.code for d in outcome.diagnostics.items]


def test_blank_symbol_cell_is_drift_not_an_untickered_class() -> None:
    raw = fixture_path("browse_edgar_series_0000002663.html").read_bytes()
    drifted = raw.replace(
        b'<td class="text-sm">Class S</td>',
        b'<td class="text-sm">Class S</td>\n<td class="text-sm"></td>',
    )
    assert drifted != raw

    outcome = parse_browse_series_page(
        BrowsePageInput("0000002663", browse_series_url(2663), drifted)
    )

    assert isinstance(outcome, BrowseParseFailure)
    codes = [d.code for d in outcome.diagnostics.items]
    assert "empty_symbol_cell" in codes


def test_truncated_page_fails_on_the_count_check() -> None:
    raw = fixture_path("browse_edgar_series_0000003521.html").read_bytes()
    outcome = parse_browse_series_page(
        BrowsePageInput("0000003521", browse_series_url(3521), raw[: len(raw) // 2])
    )

    assert isinstance(outcome, BrowseParseFailure)


def test_unsupported_encoding_is_a_failure() -> None:
    outcome = parse_browse_series_page(
        BrowsePageInput("0000002663", browse_series_url(2663), b"\xff\xfe\x00bad")
    )

    assert isinstance(outcome, BrowseParseFailure)
    assert [d.code for d in outcome.diagnostics.items] == ["unsupported_encoding"]


def test_invalid_input_cik_raises() -> None:
    with pytest.raises(ValueError, match="not numeric"):
        parse_browse_series_page(
            BrowsePageInput("S000008702", browse_series_url(2663), b"")
        )


def test_fingerprint_is_versioned() -> None:
    assert PARSER_FINGERPRINT == "browse-series-v1"
