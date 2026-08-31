"""Form 8-K family stub and refetch evaluator."""

from __future__ import annotations

from ....core.schemas import DocumentLocator
from ..base import DecisionAction, FormEvaluator, PreprocessedDocument, RefetchDecision


class Form8KEvaluator(FormEvaluator):
    """Evaluator for Form 8-K, 8-K12B, and 8-K12G3 filings."""

    def evaluate(
        self,
        preprocessed: PreprocessedDocument,
        locator: DocumentLocator,
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


__all__ = ["Form8KEvaluator"]
