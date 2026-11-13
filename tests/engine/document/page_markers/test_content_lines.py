"""The shared line predicates in their one home: content_lines."""

from __future__ import annotations

import pytest

from edgar_sec.engine.document.page_markers.content_lines import (
    is_date_line,
    is_number_or_date_line,
    is_statement_title,
)


@pytest.mark.parametrize(
    "line",
    [
        "December 31, 2008",
        "December 31, 2008 (unaudited)",
        "December 31, 2008 (continued)",
        # A month-year line parses as one date, so the core admits it.
        "December 2024",
    ],
)
def test_is_date_line_accepts_a_whole_line_date(line: str) -> None:
    assert is_date_line(line) is True


@pytest.mark.parametrize(
    "line",
    [
        # Figures are data, not a date: the split between the two predicates is deliberate.
        "1,234 5,678",
        # A numeric date's slashes survive the date-token strip, so it is not a date line.
        "12/31/2008",
        "Notes to Financial Statements December 31, 2008",
        "December 31, 2008 and 2007",
        # A bare qualifier word rides the line as prose; only the parenthesized form strips.
        "December 31, 2008 unaudited",
    ],
)
def test_is_date_line_refuses_non_dates(line: str) -> None:
    assert is_date_line(line) is False


@pytest.mark.parametrize(
    "line",
    [
        "1,234 5,678",
        "2007 2008",
        "December 31, 2008 (unaudited)",
        "12/31/2008",
        # One core: the broad predicate contains every date line, qualifiers included.
        "December 31, 2008 (continued)",
        "December 2024",
    ],
)
def test_is_number_or_date_line_accepts_figure_and_date_lines(line: str) -> None:
    assert is_number_or_date_line(line) is True


@pytest.mark.parametrize(
    "line",
    [
        # A lone page label stays furniture-shaped, and prose never qualifies.
        "60",
        "Page 60",
        "Fund Asset Allocation",
        # Bare-digit tokens are years or addresses, not amounts: commas say otherwise.
        "123 456",
        "1234.56 789.10",
        # One core: a bare qualifier word rides the line as prose and no longer qualifies.
        "December 31, 2008 unaudited",
    ],
)
def test_is_number_or_date_line_refuses_labels_and_prose(line: str) -> None:
    assert is_number_or_date_line(line) is False


@pytest.mark.parametrize(
    "template",
    [
        "consolidated statements of operations (continued)",
        "notes to financial statement",
        "balance sheet",
        "condensed consolidated balance sheets",
    ],
)
def test_is_statement_title_matches_the_title_vocabulary(template: str) -> None:
    assert is_statement_title(template) is True


@pytest.mark.parametrize(
    "template",
    ["summit global investments", "company management (unaudited) (continued)"],
)
def test_is_statement_title_refuses_other_heads(template: str) -> None:
    assert is_statement_title(template) is False
