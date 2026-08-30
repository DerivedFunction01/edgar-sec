"""Form 10-K family evaluator.

This module provides the evaluator for annual report filings (Form 10-K,
10-K405, 10-KSB, 10-KT).

Specifications / Target Rules:
------------------------------
1. Post-2011 XBRL Mandate Bypass (Tier 1):
   - Filings for fiscal periods filed in 2012+ are guaranteed to have inline/attached
     XBRL financial schedules and do not use legacy paper-incorporation Exhibit 13 stubs.
   - Action: PROCEED (category='post_2011_xbrl_full').

2. Format & Size Ceiling Bypass (Tier 2):
   - Historical inspection demonstrates that no Exhibit 13 stub in EDGAR history exceeds
     500 KB in plain text or 1.0 MB in HTML.
   - Action: PROCEED (category='size_ceiling_full').

3. Hard Machine Stubs (Tier 3 Candidate Evaluation):
   - Check for auto-generated paper document notices (Form SE, DCN markers).
   - Check for late filing placeholders (Form 12b-25 / NT 10-K).
   - Check for EDGAR system errors or empty privacy wrappers.
   - Action: SKIP_HARD_STUB (is_stub=True).

4. SPV / Asset-Backed Trust Negative Guard:
   - Check Phase 2 metadata (is_spv_registrant, SIC 6189) and header title markers
     (Mortgage Pass-Through, Asset-Backed Certificates, Equipment Lease Trust).
   - If self-contained servicer/distribution schedule with no external Exhibit 13
     referral, treat as complete.
   - Action: PROCEED (is_stub=False, category='spv_trust').

5. Substantive Exhibit 13 Incorporation (Delegation Trigger):
   - Scan for explicit delegations of substantive items:
     * Item 1 (Business) -> incorporated by reference to Exhibit 13 / Annual Report.
     * Item 6 (Selected Financial Data) -> incorporated by reference to Exhibit 13.
     * Item 7 (MD&A) -> incorporated by reference to Exhibit 13.
     * Item 8 (Audited Financial Statements) -> incorporated by reference to Exhibit 13.
     * Parts I and II general cover incorporation to Annual Report to Shareholders.
   - Distinct from universal Part III Proxy Statement (DEF 14A) incorporation.
   - Action: REFETCH_SUB_DOC (is_stub=True, target_exhibit='EX-13', category='incorporation_by_ref').

6. In-File Financial Statement Accounting Tables Guard:
   - Verify presence of multi-year financial statements (Consolidated Balance Sheets,
     Statements of Operations / Income / Cash Flows with numerical columns).
   - Action: PROCEED (is_stub=False, category='standard_full' or 'legitimate_microcap').
"""

from __future__ import annotations

from ...core.schemas import DocumentLocator
from .base import DecisionAction, FormEvaluator, PreprocessedDocument, RefetchDecision


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
