"""Current report (Form 8-K) stub and refetch evaluator.

An 8-K has no annual report to delegate to, so its evaluator proceeds unconditionally
with the primary document payload and records the standard decision category.
"""

from __future__ import annotations

from edgar_sec.domain.forms.common.decisions import DecisionAction, EvaluatorDecision


def evaluate_current(text: str) -> EvaluatorDecision:
    """Proceed with a Form 8-K/6-K's primary payload, unconditionally."""
    _ = text
    return EvaluatorDecision(
        action=DecisionAction.PROCEED,
        target_exhibit=None,
        reason="Form 8-K candidate evaluated; proceeding with primary payload.",
        is_stub=False,
        category="standard_full",
        confidence=1.0,
    )


__all__ = ["evaluate_current"]
