"""Form 10-K family stub and refetch evaluator."""

from __future__ import annotations

import re

from defs.regex import build_alternation

from ....core.schemas import DocumentLocator
from ..base import DecisionAction, FormEvaluator, PreprocessedDocument, RefetchDecision

# Optimized anchor pattern: rare in documents (0-2 occurrences)
_EX13_VARIANTS = [
    r"exhibit\s*(?:13|[-–—]\s*13|\(\s*13\s*\))(?:\.\d+)?",
    r"ex-13(?:\.\d+)?",
]
_RE_EX13 = re.compile(r"(?i)\b" + build_alternation(_EX13_VARIANTS) + r"\b")

# Delegation verb pattern checked strictly within localized windows
_DELEGATION_VERBS = [
    r"incorporated\s+(?:herein\s+)?by\s+reference",
    r"herein\s+incorporated",
    r"is\s+incorporated",
    r"are\s+incorporated",
    r"set\s+forth\s+(?:in|on)",
    r"appearing\s+in",
    r"included\s+in",
    r"filed\s+herewith\s+as",
    r"filed\s+as\s+(?:an?\s+)?exhibit",
    r"reference\s+(?:is\s+)?(?:hereby\s+)?made\s+to",
    r"refer\s+to",
]
_RE_DELEGATION_VERB = re.compile(
    r"(?i)\b" + build_alternation(_DELEGATION_VERBS) + r"\b"
)


class Form10KEvaluator(FormEvaluator):
    """Evaluator for Form 10-K, 10-K405, 10-KSB, and 10-KT filings.

    Evaluates whether the primary 10-K document is complete or an incomplete
    stub delegating substantive disclosures to Exhibit 13 or the Annual Report
    to Shareholders.
    """

    def evaluate(
        self,
        preprocessed: PreprocessedDocument,
        locator: DocumentLocator,
    ) -> RefetchDecision:
        """Evaluate a Form 10-K filing document.

        Lifecycle:
            fetch -> parse (doc 10-K) -> stub? -> refetch -> parse (doc 10-K already done, Ex-13) -> store.
        """
        _ = locator

        # Tier 1: Post-2011 XBRL mandate bypass (zero text operations for ~65% of filings)
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

        text = preprocessed.cleaned_text or preprocessed.raw_text
        if not text:
            return RefetchDecision(
                action=DecisionAction.PROCEED,
                target_exhibit=None,
                reason="Empty document text; proceeding with primary payload.",
                is_stub=False,
                category="empty_payload",
                confidence=1.0,
            )

        # Tier 2: Fast linear anchor scan (bypasses ~92% of pre-2012 filings with no regex backtracking)
        if not _RE_EX13.search(text):
            return RefetchDecision(
                action=DecisionAction.PROCEED,
                target_exhibit=None,
                reason="No Exhibit 13 reference found; standard complete filing.",
                is_stub=False,
                category="standard_full",
                confidence=1.0,
            )

        # Tier 3: Anchor-centered window slice (+/- 300 chars around each Exhibit 13 occurrence)
        for m in _RE_EX13.finditer(text):
            w_start = max(0, m.start() - 300)
            w_end = min(len(text), m.end() + 300)
            window = text[w_start:w_end]

            m_del = _RE_DELEGATION_VERB.search(window)
            if m_del:
                char_start = w_start + m_del.start()
                char_end = w_start + m_del.end()
                line_num = text.count("\n", 0, m.start()) + 1

                # Center snippet on the anchor and delegation
                snip_start = min(w_start + m_del.start(), m.start())
                snip_end = max(w_start + m_del.end(), m.end())
                lead = max(0, snip_start - 40)
                trail = min(len(text), snip_end + 40)
                snippet = " ".join(text[lead:trail].split())

                return RefetchDecision(
                    action=DecisionAction.REFETCH_SUB_DOC,
                    target_exhibit="EX-13",
                    reason=f"Exhibit 13 delegation detected at line {line_num}: '{snippet}'",
                    is_stub=True,
                    category="exhibit_13_delegation",
                    confidence=1.0,
                    metadata={
                        "char_span": (char_start, char_end),
                        "anchor_span": (m.start(), m.end()),
                        "line_number": line_num,
                        "snippet": snippet,
                    },
                )

        # If Exhibit 13 is mentioned (e.g. listed in Item 15 exhibit index) without delegation language
        return RefetchDecision(
            action=DecisionAction.PROCEED,
            target_exhibit=None,
            reason="Exhibit 13 listed in index without substantive delegation.",
            is_stub=False,
            category="exhibit_index_only",
            confidence=1.0,
        )


__all__ = ["Form10KEvaluator"]
