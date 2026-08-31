"""Form 10-Q family stub and refetch evaluator."""

from __future__ import annotations

from ....core.schemas import DocumentLocator
from ..base import DecisionAction, FormEvaluator, PreprocessedDocument, RefetchDecision


class Form10QEvaluator(FormEvaluator):
    """Evaluator for Form 10-Q, 10-QSB, and 10-QT filings."""

    def evaluate(
        self,
        preprocessed: PreprocessedDocument,
        locator: DocumentLocator,
    ) -> RefetchDecision:
        """Evaluate a Form 10-Q filing document."""
        _ = locator

        # Tier 1: Post-2011 XBRL mandate bypass
        filing_year = preprocessed.metadata.get("filing_year")
        if filing_year is not None and int(filing_year) >= 2012:
            return RefetchDecision(
                action=DecisionAction.PROCEED,
                target_exhibit=None,
                reason="Post-2011 XBRL mandate: guaranteed self-contained quarterly filing.",
                is_stub=False,
                category="post_2011_xbrl_full",
                confidence=1.0,
            )

        # Tier 2: Format & size ceiling bypass (HTML > 750KB, TXT > 300KB)
        raw_len = len(preprocessed.raw_text)
        if (preprocessed.has_html_tags and raw_len > 750_000) or (
            not preprocessed.has_html_tags and raw_len > 300_000
        ):
            return RefetchDecision(
                action=DecisionAction.PROCEED,
                target_exhibit=None,
                reason="Above size ceiling: self-contained quarterly payload.",
                is_stub=False,
                category="size_ceiling_full",
                confidence=1.0,
            )

        # Tier 3: Pre-2011 Candidate evaluation (default PROCEED placeholder)
        return RefetchDecision(
            action=DecisionAction.PROCEED,
            target_exhibit=None,
            reason="Form 10-Q candidate evaluated; proceeding with primary payload.",
            is_stub=False,
            category="standard_full",
            confidence=1.0,
        )


__all__ = ["Form10QEvaluator"]
