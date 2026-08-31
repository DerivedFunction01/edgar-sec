"""Form 10-K family stub and refetch evaluator."""

from __future__ import annotations

from ....core.schemas import DocumentLocator
from ..base import DecisionAction, FormEvaluator, PreprocessedDocument, RefetchDecision


class Form10KEvaluator(FormEvaluator):
    """Evaluator for Form 10-K, 10-K405, 10-KSB, and 10-KT filings."""

    def evaluate(
        self,
        preprocessed: PreprocessedDocument,
        locator: DocumentLocator,
    ) -> RefetchDecision:
        """Evaluate a Form 10-K filing document."""
        _ = locator

        # Tier 1: Post-2011 XBRL mandate bypass
        filing_year = preprocessed.metadata.get("filing_year")
        if filing_year is not None and int(filing_year) >= 2012:
            return RefetchDecision(
                action=DecisionAction.PROCEED,
                target_exhibit=None,
                reason="Post-2011 XBRL mandate: guaranteed self-contained periodic filing.",
                is_stub=False,
                category="post_2011_xbrl_full",
                confidence=1.0,
            )

        # Tier 2: Format & size ceiling bypass (HTML > 1MB, TXT > 500KB)
        raw_len = len(preprocessed.raw_text)
        if (preprocessed.has_html_tags and raw_len > 1_000_000) or (
            not preprocessed.has_html_tags and raw_len > 500_000
        ):
            return RefetchDecision(
                action=DecisionAction.PROCEED,
                target_exhibit=None,
                reason="Above size ceiling: self-contained payload.",
                is_stub=False,
                category="size_ceiling_full",
                confidence=1.0,
            )

        # Tier 3: Pre-2011 Candidate evaluation (default PROCEED placeholder)
        return RefetchDecision(
            action=DecisionAction.PROCEED,
            target_exhibit=None,
            reason="Form 10-K candidate evaluated; proceeding with primary payload.",
            is_stub=False,
            category="standard_full",
            confidence=1.0,
        )


__all__ = ["Form10KEvaluator"]
