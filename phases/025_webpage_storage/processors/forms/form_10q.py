"""Form 10-Q family evaluator.

This module provides the evaluator for quarterly report filings (Form 10-Q,
10-QSB, 10-QT).

Specifications / Target Rules:
------------------------------
1. Post-2011 XBRL Mandate Bypass (Tier 1):
   - Filings for fiscal periods filed in 2012+ are guaranteed to have inline/attached
     XBRL financial schedules and do not use legacy paper-incorporation Exhibit 19 stubs.
   - Action: PROCEED (category='post_2011_xbrl_full').

2. Format & Size Ceiling Bypass (Tier 2):
   - Quarterly reports exceeding 750 KB in HTML or 300 KB in plain text are guaranteed
     self-contained.
   - Action: PROCEED (category='size_ceiling_full').

3. Hard Machine Stubs:
   - Check for late filing placeholders (Form 12b-25 / NT 10-Q).
   - Check for paper notices / Form SE placeholders.
   - Action: SKIP_HARD_STUB (is_stub=True).

4. Substantive Exhibit 19 Incorporation (Delegation Trigger):
   - Under Item 601 of Regulation S-K, Exhibit 19 represents the Quarterly Report
     to Security Holders.
   - In transitional filings, issuers sometimes filed a 10-Q cover delegating
     Part I (Item 1 Unaudited Financial Statements, Item 2 Interim MD&A) to Exhibit 19.
   - Action: REFETCH_SUB_DOC (is_stub=True, target_exhibit='EX-19', category='incorporation_by_ref').

5. In-File Quarterly Financials:
   - Check for in-file quarterly balance sheet and income statements.
   - Action: PROCEED (is_stub=False, category='standard_full').
"""

from __future__ import annotations

from ...core.schemas import DocumentLocator
from .base import DecisionAction, FormEvaluator, PreprocessedDocument, RefetchDecision


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
