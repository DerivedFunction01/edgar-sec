"""Tests for the quarterly report stub/refetch evaluator."""

from __future__ import annotations

from edgar_sec.domain.forms.decisions import DecisionAction
from edgar_sec.engine.forms.evaluators.base import ASCII_SIZE_CEILING, EvaluatorInput
from edgar_sec.engine.forms.evaluators.quarterly import evaluate_quarterly


def test_post_2011_bypasses() -> None:
    decision = evaluate_quarterly(EvaluatorInput(text="anything", filing_year=2015))
    assert decision.action == DecisionAction.PROCEED
    assert decision.category == "post_2011_xbrl_full"


def test_large_ascii_payload_bypasses() -> None:
    decision = evaluate_quarterly(
        EvaluatorInput(text="", raw_text="x" * (ASCII_SIZE_CEILING + 1))
    )
    assert decision.action == DecisionAction.PROCEED
    assert decision.category == "size_ceiling_full"


def test_small_payload_proceeds_as_standard() -> None:
    decision = evaluate_quarterly(EvaluatorInput(text="small", filing_year=2005))
    assert decision.action == DecisionAction.PROCEED
    assert decision.category == "standard_full"


def test_never_requests_a_refetch() -> None:
    for year in (None, 2005, 2015):
        decision = evaluate_quarterly(EvaluatorInput(text="body", filing_year=year))
        assert decision.action is not DecisionAction.REFETCH_SUB_DOC
        assert decision.target_exhibit is None


def test_bare_string_accepted() -> None:
    assert evaluate_quarterly("body").action == DecisionAction.PROCEED
