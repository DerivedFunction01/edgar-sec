"""Unit tests for form evaluator decisions and actions."""

from edgar_sec.domain.forms.decisions import (
    DecisionAction,
    EvaluatorDecision,
)


def test_decision_actions() -> None:
    assert DecisionAction.PROCEED == "proceed"
    assert DecisionAction.REFETCH_SUB_DOC == "refetch_sub_doc"
    assert DecisionAction.SKIP_HARD_STUB == "skip_hard_stub"


def test_evaluator_decision_model() -> None:
    decision = EvaluatorDecision(
        action=DecisionAction.REFETCH_SUB_DOC,
        target_exhibit="ex13.htm",
        reason="10-K delegates financial statements to Exhibit 13",
        is_stub=True,
    )
    assert decision.action == DecisionAction.REFETCH_SUB_DOC
    assert decision.target_exhibit == "ex13.htm"
    assert decision.is_stub is True
    assert decision.confidence == 1.0
