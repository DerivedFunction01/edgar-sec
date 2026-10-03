"""Annual report (Form 10-K family) stub and refetch evaluator: it decides whether a
filing delegates its financial statements to Exhibit 13. Post-2011 XBRL filings are
self-contained by construction and skip the scan entirely.
"""

from __future__ import annotations

import re

from edgar_sec.domain.forms.common.decisions import DecisionAction, EvaluatorDecision
from edgar_sec.foundation.regex.builder import build_alternation

#: Rare in documents, so the scan that looks for them is cheap.
_EX13_VARIANTS = [
    r"exhibit\s*(?:13|[-–—]\s*13|\(\s*13\s*\))(?:\.\d+)?",
    r"ex-13(?:\.\d+)?",
]
_RE_EX13 = re.compile(r"(?i)\b" + build_alternation(_EX13_VARIANTS) + r"\b")

#: Checked strictly within the anchor-centred window, never against the document.
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

#: Characters of context either side of an anchor before the window is judged.
_WINDOW_CHARS = 300

#: Characters of context either side of the matched span when quoting the reason.
_SNIPPET_CHARS = 40


def evaluate_annual(
    text: str,
    *,
    filing_year: int | str | None = None,
) -> EvaluatorDecision:
    """Whether an annual report is complete or delegates to Exhibit 13. `text` is the
    normalized primary document; a `filing_year` at or past 2012 ends the decision.
    """
    if filing_year is not None and int(filing_year) >= 2012:
        return EvaluatorDecision(
            action=DecisionAction.PROCEED,
            target_exhibit=None,
            reason="Post-2011 XBRL mandate: guaranteed self-contained periodic filing.",
            is_stub=False,
            category="post_2011_xbrl_full",
            confidence=1.0,
        )

    if not text:
        return EvaluatorDecision(
            action=DecisionAction.PROCEED,
            target_exhibit=None,
            reason="Empty document text; proceeding with primary payload.",
            is_stub=False,
            category="empty_payload",
            confidence=1.0,
        )

    if not _RE_EX13.search(text):
        return EvaluatorDecision(
            action=DecisionAction.PROCEED,
            target_exhibit=None,
            reason="No Exhibit 13 reference found; standard complete filing.",
            is_stub=False,
            category="standard_full",
            confidence=1.0,
        )

    for match in _RE_EX13.finditer(text):
        window_start = max(0, match.start() - _WINDOW_CHARS)
        window_end = min(len(text), match.end() + _WINDOW_CHARS)
        window = text[window_start:window_end]

        delegation = _RE_DELEGATION_VERB.search(window)
        if delegation is None:
            continue

        char_start = window_start + delegation.start()
        char_end = window_start + delegation.end()
        line_number = text.count("\n", 0, match.start()) + 1

        snippet_start = min(window_start + delegation.start(), match.start())
        snippet_end = max(window_start + delegation.end(), match.end())
        lead = max(0, snippet_start - _SNIPPET_CHARS)
        trail = min(len(text), snippet_end + _SNIPPET_CHARS)
        snippet = " ".join(text[lead:trail].split())

        return EvaluatorDecision(
            action=DecisionAction.REFETCH_SUB_DOC,
            target_exhibit="EX-13",
            reason=f"Exhibit 13 delegation detected at line {line_number}: '{snippet}'",
            is_stub=True,
            category="exhibit_13_delegation",
            confidence=1.0,
            metadata={
                "char_span": (char_start, char_end),
                "anchor_span": (match.start(), match.end()),
                "line_number": line_number,
                "snippet": snippet,
            },
        )

    return EvaluatorDecision(
        action=DecisionAction.PROCEED,
        target_exhibit=None,
        reason="Exhibit 13 listed in index without substantive delegation.",
        is_stub=False,
        category="exhibit_index_only",
        confidence=1.0,
    )


__all__ = ["evaluate_annual"]
