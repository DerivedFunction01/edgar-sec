"""Contract tests for the current-report evaluator."""

from __future__ import annotations

import inspect

import pytest

from edgar_sec.domain.forms.common.decisions import DecisionAction
from edgar_sec.engine.forms.plugins.base import evaluate_generic
from edgar_sec.engine.forms.plugins.evaluators.current import (
    evaluate_current,
)


def test_a_current_report_always_proceeds() -> None:
    decision = evaluate_current("normalized text")
    assert decision.action is DecisionAction.PROCEED
    assert decision.target_exhibit is None
    assert decision.is_stub is False
    assert decision.category == "standard_full"
    assert decision.confidence == 1.0
    assert decision.metadata == {}
    assert "Form 8-K candidate evaluated" in decision.reason


@pytest.mark.parametrize(
    "text",
    [
        "",
        "Item 2.02 Results of Operations",
        "Item 5.07 Submission of Matters to a Vote of Security Holders",
        "Exhibit 13 is incorporated by reference into this report.",
        "x" * 1_000_000,
    ],
)
def test_the_document_is_never_read(text: str) -> None:
    """Both arguments are discarded; every 8-K gets the same decision."""
    assert evaluate_current(text) == evaluate_current("")


def test_the_reason_names_the_8k_path() -> None:
    """Folding this into the generic evaluator would lose which path ran."""
    assert "Form 8-K" in evaluate_current("").reason
    assert "Generic" in evaluate_generic("").reason


def test_the_signature_takes_only_the_normalized_text() -> None:
    """The shared evaluator contract is callable with one positional argument."""
    assert list(inspect.signature(evaluate_current).parameters) == ["text"]
