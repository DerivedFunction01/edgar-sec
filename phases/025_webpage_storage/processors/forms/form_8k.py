"""Form 8-K family evaluator stub.

This module provides the stub evaluator for current report filings (Form 8-K,
8-K12B, 8-K12G3).

Specifications / Target Rules:
------------------------------
1. Item 2.02 (Results of Operations and Financial Condition) & Item 7.01 (Regulation FD):
   - In most 8-K earnings release filings, the primary 8-K document is a 1-page transmittal
     referencing Exhibit 99.1 (the full earnings press release and tables).
   - If Item 2.02 or Item 7.01 is declared and the primary document contains no substantive
     tables, delegate to Exhibit 99.1.
   - Action: REFETCH_SUB_DOC (is_stub=True, target_exhibit='EX-99.1', category='incorporation_by_ref').

2. Major Transaction / Merger Filings (Item 1.01, 2.01):
   - Check if substantive agreements are in Exhibit 2.1 or Exhibit 10.1.

3. Standard Narrative 8-K:
   - Self-contained narrative items (e.g. Item 5.02 Departure of Directors/Officers).
   - Action: PROCEED (is_stub=False, category='standard_full').
"""

from __future__ import annotations

from ...core.schemas import DocumentLocator
from .base import DecisionAction, FormEvaluator, PreprocessedDocument, RefetchDecision


class Form8KEvaluator(FormEvaluator):
    """Evaluator for Form 8-K, 8-K12B, and 8-K12G3 filings."""

    def evaluate(
        self,
        preprocessed: PreprocessedDocument,
        locator: DocumentLocator,
    ) -> RefetchDecision:
        """Evaluate a Form 8-K filing document.

        Currently a no-op placeholder returning PROCEED by default until active
        form-specific rules are finalized.
        """
        # No-op pass-through implementation
        return RefetchDecision(
            action=DecisionAction.PROCEED,
            target_exhibit=None,
            reason="Form 8-K no-op evaluation placeholder; proceeding with primary payload.",
            is_stub=False,
            category="standard_full",
            confidence=1.0,
        )
