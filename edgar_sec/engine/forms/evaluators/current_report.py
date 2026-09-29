"""Current report (Form 8-K) stub and refetch evaluator.

An 8-K body is a short item list, and its exhibits are referenced rather than
incorporated. The evaluator is therefore a pass-through: there is no
substantive disclosure to recover by fetching an exhibit, and the exhibits that
matter (Item 9.01 lists) are indexed inside the same document.
"""

from __future__ import annotations

from edgar_sec.domain.forms.decisions import EvaluatorDecision
from edgar_sec.engine.forms.evaluators.base import (
    EvaluatorInput,
    proceed,
)


def evaluate_current_report(payload: str | EvaluatorInput) -> EvaluatorDecision:
    """Evaluate a current report; always proceeds with the primary payload."""
    _ = EvaluatorInput.coerce(payload)
    return proceed(
        "Form 8-K candidate evaluated; proceeding with primary payload.",
        "standard_full",
    )


__all__ = ["evaluate_current_report"]
