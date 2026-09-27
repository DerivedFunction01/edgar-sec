"""Current report (Form 8-K) stub and refetch evaluator."""

from __future__ import annotations

from typing import Any

from defs.sec_documents.models import PreprocessedDocument
from defs.sec_forms.forms.evaluator import (
    DecisionAction,
    FormEvaluator,
    RefetchDecision,
)


class CurrentReportEvaluator(FormEvaluator):
    """Evaluator for Form 8-K, 8-K12B, and 8-K12G3 filings."""

    def evaluate(
        self,
        preprocessed: PreprocessedDocument,
        locator: Any = None,
    ) -> RefetchDecision:
        """Evaluate a Form 8-K filing document."""
        _ = locator
        _ = preprocessed
        return RefetchDecision(
            action=DecisionAction.PROCEED,
            target_exhibit=None,
            reason="Form 8-K candidate evaluated; proceeding with primary payload.",
            is_stub=False,
            category="standard_full",
            confidence=1.0,
        )


Form8KEvaluator = CurrentReportEvaluator

__all__ = ["CurrentReportEvaluator", "Form8KEvaluator"]
