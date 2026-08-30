"""Generic fallback form evaluator stub.

This module provides the fallback evaluator for all unspecified form types
(Form 20-F, 11-K, 6-K, Form 3/4/5, Form 144, SC 13D/G, etc.).

Specifications / Target Rules:
------------------------------
1. Universal Hard Machine Stubs:
   - Form 12b-25 / Notification of Late Filing.
   - Form SE / Auto-generated paper submission notices with Document Control Numbers.
   - Privacy-enhanced message wrappers (<300 words, undecodable).
   - EDGAR system error pages.
   - Action: SKIP_HARD_STUB (is_stub=True, category='index_stub' or 'paper_notice').

2. Default Pass-Through:
   - All other valid documents proceed with primary content.
   - Action: PROCEED (is_stub=False, category='standard_full').
"""

from __future__ import annotations

from ...core.schemas import DocumentLocator
from .base import DecisionAction, FormEvaluator, PreprocessedDocument, RefetchDecision


class GenericFormEvaluator(FormEvaluator):
    """Fallback evaluator for all generic/unspecified form types."""

    def evaluate(
        self,
        preprocessed: PreprocessedDocument,
        locator: DocumentLocator,
    ) -> RefetchDecision:
        """Evaluate a generic filing document.

        Currently a no-op placeholder returning PROCEED by default until active
        rules are finalized.
        """
        # No-op pass-through implementation
        return RefetchDecision(
            action=DecisionAction.PROCEED,
            target_exhibit=None,
            reason="Generic form no-op evaluation placeholder; proceeding with primary payload.",
            is_stub=False,
            category="standard_full",
            confidence=1.0,
        )
