"""Tests for the current report stub/refetch evaluator."""

from __future__ import annotations

from edgar_sec.domain.forms.decisions import DecisionAction
from edgar_sec.engine.forms.evaluators.base import EvaluatorInput
from edgar_sec.engine.forms.evaluators.current_report import (
    evaluate_current_report,
)


def test_always_proceeds() -> None:
    decision = evaluate_current_report("Item 5.02 Departure of Directors")
    assert decision.action == DecisionAction.PROCEED
    assert decision.is_stub is False
    assert decision.target_exhibit is None
    assert decision.category == "standard_full"


def test_accepts_structured_input() -> None:
    decision = evaluate_current_report(EvaluatorInput(text="body", filing_year=2015))
    assert decision.action == DecisionAction.PROCEED


def test_never_requests_a_refetch() -> None:
    decision = evaluate_current_report("Item 9.01 exhibits are listed herein")
    assert decision.action is not DecisionAction.REFETCH_SUB_DOC
