"""Tests for the annual report stub/refetch evaluator."""

from __future__ import annotations

from edgar_sec.domain.forms.decisions import DecisionAction
from edgar_sec.engine.forms.evaluators.annual import RE_EX13, evaluate_annual
from edgar_sec.engine.forms.evaluators.base import EvaluatorInput

STUB = """\
PART III

ITEM 13. Certain Relationships and Related Transactions

Part III of this report, and the financial statements included therein, are \
incorporated herein by reference to Exhibit 13, the Annual Report on Form \
10-K filed herewith.

SIGNATURES"""

INDEX_ONLY = """\
PART IV

ITEM 15. Exhibits and Financial Statement Schedules

13. Annual Report on Form 10-K (see Exhibit 13).

SIGNATURES"""

NO_EX13 = "This report contains no annex, addendum, or attached statement."


def test_post_2011_filing_bypasses_content_scan() -> None:
    decision = evaluate_annual(EvaluatorInput(text=STUB, filing_year=2015))
    assert decision.action == DecisionAction.PROCEED
    assert decision.category == "post_2011_xbrl_full"


def test_exhibit_13_delegation_requests_refetch() -> None:
    decision = evaluate_annual(EvaluatorInput(text=STUB, filing_year=2005))
    assert decision.action == DecisionAction.REFETCH_SUB_DOC
    assert decision.target_exhibit == "EX-13"
    assert decision.is_stub is True
    assert decision.category == "exhibit_13_delegation"
    assert "line_number" in decision.metadata
    assert decision.metadata["line_number"] > 0


def test_exhibit_index_only_proceeds() -> None:
    """An Exhibit 13 mention with no delegation verb nearby is just the index."""
    decision = evaluate_annual(EvaluatorInput(text=INDEX_ONLY, filing_year=2005))
    assert decision.action == DecisionAction.PROCEED
    assert decision.category == "exhibit_index_only"


def test_no_anchor_proceeds_as_standard() -> None:
    decision = evaluate_annual(EvaluatorInput(text=NO_EX13, filing_year=2005))
    assert decision.action == DecisionAction.PROCEED
    assert decision.category == "standard_full"


def test_empty_payload_proceeds() -> None:
    decision = evaluate_annual(EvaluatorInput(text="", filing_year=2005))
    assert decision.action == DecisionAction.PROCEED
    assert decision.category == "empty_payload"


def test_bare_string_payload_is_accepted() -> None:
    decision = evaluate_annual(NO_EX13)
    assert decision.action == DecisionAction.PROCEED


def test_ex13_anchor_forms() -> None:
    for form in (
        "Exhibit 13",
        "EX-13",
        "EXHIBIT 13.",
        "Exhibit - 13",
        "Exhibit 13.1",
        "exhibit\n13",
    ):
        assert RE_EX13.search(form), form


def test_ex13_anchor_requires_the_word_exhibit() -> None:
    # "Item 13" is a structural reference, not the exhibit anchor.
    assert not RE_EX13.search("Item 13. Certain Relationships")
    assert not RE_EX13.search("ITEM 13")


def test_no_year_defaults_to_content_scan() -> None:
    decision = evaluate_annual(STUB)
    assert decision.action == DecisionAction.REFETCH_SUB_DOC


def test_delegation_outside_the_window_does_not_trigger() -> None:
    filler = "x" * 400
    text = f"See Exhibit 13 for details.\n{filler}\n{filler}\n{filler}\n{filler}"
    decision = evaluate_annual(EvaluatorInput(text=text, filing_year=2005))
    assert decision.action == DecisionAction.PROCEED
    assert decision.category == "exhibit_index_only"
