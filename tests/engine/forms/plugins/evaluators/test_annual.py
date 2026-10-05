"""Contract tests for the annual-report stub and refetch evaluator."""

from __future__ import annotations

import pytest

from edgar_sec.domain.forms.common.decisions import DecisionAction
from edgar_sec.engine.forms.plugins.evaluators.annual import evaluate_annual


def test_post_2011_xbrl_filing_skips_the_document_entirely() -> None:
    """A delegation the anchor scan would find is still reported complete, which is
    the observable proof that the text was never consulted.
    """
    decision = evaluate_annual(
        "The financial statements are set forth in Exhibit 13.",
        filing_year=2012,
    )
    assert decision.action is DecisionAction.PROCEED
    assert decision.category == "post_2011_xbrl_full"
    assert decision.is_stub is False


@pytest.mark.parametrize("year", [2011, 2010, 1999])
def test_a_pre_2012_year_does_not_take_the_xbrl_shortcut(year: int) -> None:
    decision = evaluate_annual(
        "The financial statements are set forth in Exhibit 13.", filing_year=year
    )
    assert decision.category == "exhibit_13_delegation"


def test_a_string_filing_year_is_coerced_like_v1() -> None:
    decision = evaluate_annual("", filing_year="2013")
    assert decision.category == "post_2011_xbrl_full"


def test_empty_document_is_reported_as_an_empty_payload() -> None:
    decision = evaluate_annual("")
    assert decision.action is DecisionAction.PROCEED
    assert decision.category == "empty_payload"
    assert decision.is_stub is False
    assert decision.target_exhibit is None


def test_a_document_without_an_exhibit_13_anchor_is_complete() -> None:
    decision = evaluate_annual("Item 1. Business\nWe make widgets.")
    assert decision.category == "standard_full"
    assert decision.is_stub is False
    assert "No Exhibit 13 reference found" in decision.reason


@pytest.mark.parametrize(
    "anchor",
    [
        "Exhibit 13",
        "EXHIBIT 13",
        "exhibit-13",
        "Exhibit - 13",
        "Exhibit 13.1",
        "EX-13",
        "EX-13.1",
    ],
)
def test_every_exhibit_13_spelling_is_an_anchor(anchor: str) -> None:
    decision = evaluate_annual(f"See {anchor}. The statements are incorporated herein.")
    assert decision.category == "exhibit_13_delegation"
    assert decision.metadata["snippet"]


@pytest.mark.parametrize(
    "near_miss", ["Exhibit 130", "Exhibit 12", "Exhibit 1", "ex-130"]
)
def test_a_numbered_exhibit_above_13_is_not_an_anchor(near_miss: str) -> None:
    assert evaluate_annual(f"See {near_miss}.").category == "standard_full"


def test_the_parenthesised_spelling_is_unreachable_in_v1() -> None:
    """The trailing ``\b`` cannot sit between ``)`` and prose, so the variant is
    unreachable; it is kept because that wrapper rejects ``Exhibit 130``.
    """
    assert evaluate_annual("See Exhibit (13). Incorporated by reference.").category == (
        "standard_full"
    )
    assert evaluate_annual("See Exhibit (13)x incorporated by reference.").action is (
        DecisionAction.REFETCH_SUB_DOC
    )


def test_an_exhibit_number_glued_to_letters_is_not_an_anchor() -> None:
    """The trailing word boundary requires a non-word character after the number."""
    assert evaluate_annual("Exhibit 13x").category == "standard_full"
    assert evaluate_annual("Exhibit 13.").category == "exhibit_index_only"


def test_an_anchor_with_no_delegation_language_is_an_index_entry() -> None:
    decision = evaluate_annual("15. Exhibit Index\n  EX-13  Annual Report")
    assert decision.action is DecisionAction.PROCEED
    assert decision.category == "exhibit_index_only"
    assert decision.is_stub is False
    assert decision.target_exhibit is None


def test_a_delegation_beyond_the_window_is_not_found() -> None:
    text = "Exhibit 13 " + "x" * 400 + " is incorporated by reference."
    assert evaluate_annual(text).category == "exhibit_index_only"


def test_a_delegation_just_inside_the_window_is_found() -> None:
    text = "Exhibit 13 " + "x" * 200 + " is incorporated by reference."
    assert evaluate_annual(text).category == "exhibit_13_delegation"


def test_a_delegation_requests_the_exhibit() -> None:
    decision = evaluate_annual(
        "The financial statements are incorporated by reference into Exhibit 13."
    )
    assert decision.action is DecisionAction.REFETCH_SUB_DOC
    assert decision.target_exhibit == "EX-13"
    assert decision.category == "exhibit_13_delegation"
    assert decision.is_stub is True
    assert decision.confidence == 1.0


@pytest.mark.parametrize(
    "sentence",
    [
        "is incorporated herein by reference into Exhibit 13",
        "herein incorporated: Exhibit 13",
        "are incorporated by reference in Exhibit 13",
        "set forth in Exhibit 13",
        "appearing in Exhibit 13",
        "included in Exhibit 13",
        "filed herewith as Exhibit 13",
        "filed as an Exhibit 13",
        "reference is hereby made to Exhibit 13",
        "refer to Exhibit 13",
    ],
)
def test_every_delegation_verb_is_recognized(sentence: str) -> None:
    assert evaluate_annual(sentence).action is DecisionAction.REFETCH_SUB_DOC


def test_the_first_delegating_anchor_wins() -> None:
    text = (
        "Exhibit 13 is noted.\n"
        + "y" * 400
        + "\nExhibit 13 is incorporated by reference.\n"
        + "z" * 400
        + "\nExhibit 13 is incorporated by reference."
    )
    decision = evaluate_annual(text)
    anchor_start, anchor_end = decision.metadata["anchor_span"]
    assert text[anchor_start:anchor_end] == "Exhibit 13"
    assert anchor_start == text.index("Exhibit 13 is incorporated")


def test_the_reported_line_is_the_anchors_line_not_the_verbs() -> None:
    decision = evaluate_annual("\n\n\nSee Exhibit 13\n\nis incorporated by reference.")
    assert decision.metadata["line_number"] == 4


def test_the_reported_spans_are_offsets_into_the_whole_document() -> None:
    text = "z" * 350 + " is incorporated by reference. " + "q" * 250 + " Exhibit 13"
    decision = evaluate_annual(text)
    char_start, char_end = decision.metadata["char_span"]
    assert (char_start, char_end) != (0, len("is incorporated"))
    assert text[char_start:char_end] == "is incorporated"
    anchor_start, anchor_end = decision.metadata["anchor_span"]
    assert text[anchor_start:anchor_end] == "Exhibit 13"


def test_the_snippet_clips_forty_characters_either_side() -> None:
    """The snippet runs from 40 characters before the earlier of the two spans
    to 40 characters past the later one, then collapses its whitespace."""
    decision = evaluate_annual(
        "A" * 100 + " Exhibit 13 is incorporated by reference. " + "B" * 100
    )
    assert decision.metadata["snippet"] == (
        "A" * 39 + " Exhibit 13 is incorporated by reference. " + "B" * 25
    )


def test_the_snippet_is_whitespace_normalized() -> None:
    decision = evaluate_annual(
        "x" * 400 + "  Exhibit 13\n  is   incorporated by reference  " + "y" * 400
    )
    snippet = decision.metadata["snippet"]
    assert "  " not in snippet
    assert "\n" not in snippet
    assert "Exhibit 13 is incorporated by reference" in snippet
    assert snippet in decision.reason


def test_the_decision_is_deterministic_for_the_same_input() -> None:
    text = "The statements appear in Exhibit 13 and are incorporated herein."
    assert evaluate_annual(text) == evaluate_annual(text)
