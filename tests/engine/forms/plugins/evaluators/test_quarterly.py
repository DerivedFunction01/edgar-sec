"""Contract tests for the quarterly-report evaluator."""

from __future__ import annotations

import pytest

from edgar_sec.domain.forms.common.decisions import DecisionAction
from edgar_sec.engine.forms.plugins.evaluators.quarterly import (
    ASCII_SIZE_CEILING,
    HTML_SIZE_CEILING,
    evaluate_quarterly,
)


def test_an_unsupplied_year_and_length_reach_the_standard_conclusion() -> None:
    decision = evaluate_quarterly("normalized text")
    assert decision.action is DecisionAction.PROCEED
    assert decision.target_exhibit is None
    assert decision.is_stub is False
    assert decision.category == "standard_full"
    assert decision.confidence == 1.0
    assert "proceeding with primary payload" in decision.reason


def test_the_evaluator_never_concludes_a_stub() -> None:
    """v1's quarterly evaluator has no refetch and no skip path at all."""
    decisions = [
        evaluate_quarterly("", filing_year=2012),
        evaluate_quarterly("", raw_length=10**9, is_html=True),
        evaluate_quarterly("Exhibit 13 is incorporated by reference."),
        evaluate_quarterly("", filing_year="1999", raw_length=10**9),
    ]
    assert {decision.action for decision in decisions} == {DecisionAction.PROCEED}
    assert not any(decision.is_stub for decision in decisions)
    assert all(decision.target_exhibit is None for decision in decisions)


@pytest.mark.parametrize("year", [2012, 2013, 2030, "2026"])
def test_post_2011_xbrl_filings_are_claimed_complete(year: int) -> None:
    decision = evaluate_quarterly("", filing_year=year)
    assert decision.category == "post_2011_xbrl_full"
    assert "XBRL mandate" in decision.reason


@pytest.mark.parametrize("year", [2011, 2010, 2009])
def test_a_pre_2012_year_does_not_take_the_xbrl_shortcut(year: int) -> None:
    assert evaluate_quarterly("", filing_year=year).category == "standard_full"


def test_the_year_shortcut_precedes_the_size_ceiling() -> None:
    decision = evaluate_quarterly(
        "", filing_year=2015, raw_length=HTML_SIZE_CEILING + 1, is_html=True
    )
    assert decision.category == "post_2011_xbrl_full"


def test_an_html_payload_past_the_html_ceiling_is_claimed_complete() -> None:
    decision = evaluate_quarterly("", raw_length=HTML_SIZE_CEILING + 1, is_html=True)
    assert decision.category == "size_ceiling_full"
    assert "size ceiling" in decision.reason


def test_the_ceilings_are_selected_by_representation() -> None:
    """A payload past the ASCII ceiling but under the HTML one is only judged
    as oversize when the payload is ASCII, which is what ``is_html`` decides."""
    between = ASCII_SIZE_CEILING + 1
    assert between < HTML_SIZE_CEILING
    assert (
        evaluate_quarterly("", raw_length=between, is_html=False).category
        == "size_ceiling_full"
    )
    assert (
        evaluate_quarterly("", raw_length=between, is_html=True).category
        == "standard_full"
    )


def test_an_ascii_payload_past_the_ascii_ceiling_is_claimed_complete() -> None:
    decision = evaluate_quarterly("", raw_length=ASCII_SIZE_CEILING + 1)
    assert decision.category == "size_ceiling_full"


def test_the_ceilings_are_exclusive_bounds() -> None:
    assert (
        evaluate_quarterly("", raw_length=ASCII_SIZE_CEILING).category
        == "standard_full"
    )
    assert (
        evaluate_quarterly("", raw_length=HTML_SIZE_CEILING, is_html=True).category
        == "standard_full"
    )


def test_an_unsupplied_length_never_satisfies_a_ceiling() -> None:
    """The ceiling is a statement about what was fetched, not about ``text``.

    A 40-megabyte normalized frame with no raw length reported is not evidence
    that the payload was large, so the shortcut must not fire.
    """
    assert evaluate_quarterly("x" * 40_000_000).category == "standard_full"


def test_the_ceiling_reads_the_raw_length_not_the_text() -> None:
    assert evaluate_quarterly("x" * 10, raw_length=500).category == "standard_full"
