"""Annual report (Form 10-K, 20-F) stub and refetch evaluator.

Lifecycle: fetch -> parse (doc 10-K) -> stub? -> refetch -> parse (doc 10-K
already done, Ex-13) -> store.

A pre-2012 10-K may omit its financials entirely and incorporate them by
reference from Exhibit 13 (the Annual Report to Shareholders). Detecting that
requires *both* an Exhibit 13 mention and delegation language nearby; a bare
Exhibit 13 line is usually just the exhibit index, which is not a stub.
"""

from __future__ import annotations

import re

from edgar_sec.domain.forms.decisions import EvaluatorDecision
from edgar_sec.engine.forms.evaluators.base import (
    EvaluatorInput,
    proceed,
    refetch_exhibit,
)
from edgar_sec.foundation.regex.builder import build_alternation

# Optimized anchor pattern: rare in documents (0-2 occurrences).
_EX13_VARIANTS = [
    r"exhibit\s*(?:13|[-–—]\s*13|\(\s*13\s*\))(?:\.\d+)?",
    r"ex-13(?:\.\d+)?",
]
RE_EX13 = re.compile(rf"\b{build_alternation(_EX13_VARIANTS)}\b", re.IGNORECASE)

# Delegation verb pattern checked strictly within localized windows.
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
RE_DELEGATION_VERB = re.compile(
    rf"\b{build_alternation(_DELEGATION_VERBS)}\b", re.IGNORECASE
)

# Half-width of the localization window around each Exhibit 13 anchor.
_DELEGATION_WINDOW = 300


def evaluate_annual(payload: str | EvaluatorInput) -> EvaluatorDecision:
    """Evaluate an annual report for Exhibit 13 incorporation delegation."""
    data = EvaluatorInput.coerce(payload)

    # Tier 1: post-2011 XBRL mandate bypass. Zero text operations for ~65% of
    # filings, since the regime guarantees self-contained periodic filings.
    if data.is_post_xbrl:
        return proceed(
            "Post-2011 XBRL mandate: guaranteed self-contained periodic filing.",
            "post_2011_xbrl_full",
        )

    text = data.body_text
    if not text:
        return proceed(
            "Empty document text; proceeding with primary payload.", "empty_payload"
        )

    # Tier 2: fast linear anchor scan. Bypasses most pre-2012 filings with no
    # regex backtracking, because the anchor is rare in a filing body.
    if not RE_EX13.search(text):
        return proceed(
            "No Exhibit 13 reference found; standard complete filing.",
            "standard_full",
        )

    # Tier 3: anchor-centered window slice.
    for match in RE_EX13.finditer(text):
        window_start = max(0, match.start() - _DELEGATION_WINDOW)
        window_end = min(len(text), match.end() + _DELEGATION_WINDOW)
        window = text[window_start:window_end]
        delegation = RE_DELEGATION_VERB.search(window)
        if delegation is None:
            continue

        char_start = window_start + delegation.start()
        char_end = window_start + delegation.end()
        line_num = text.count("\n", 0, match.start()) + 1

        snippet_start = min(window_start + delegation.start(), match.start())
        snippet_end = max(window_start + delegation.end(), match.end())
        lead = max(0, snippet_start - 40)
        trail = min(len(text), snippet_end + 40)
        snippet = " ".join(text[lead:trail].split())

        return refetch_exhibit(
            "EX-13",
            f"Exhibit 13 delegation detected at line {line_num}: '{snippet}'",
            "exhibit_13_delegation",
            char_span=(char_start, char_end),
            anchor_span=(match.start(), match.end()),
            line_number=line_num,
            snippet=snippet,
        )

    # Exhibit 13 is mentioned (for example in the Item 15 exhibit index) with
    # no delegation language nearby: the filing is complete.
    return proceed(
        "Exhibit 13 listed in index without substantive delegation.",
        "exhibit_index_only",
    )


__all__ = ["RE_DELEGATION_VERB", "RE_EX13", "evaluate_annual"]
