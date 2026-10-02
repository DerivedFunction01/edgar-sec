"""Quarterly report (Form 10-Q) stub and refetch evaluator.

Evaluates Form 10-Q documents to classify completeness categories.
Evaluation employs two fast paths when metadata is supplied:
1. Post-2011 XBRL mandate: Guaranteed self-contained filing.
2. Size ceiling check: Large raw payloads exceeding HTML/ASCII size thresholds
   are assumed complete.
When evaluated on normalized text alone without metadata shortcuts,
evaluates to the standard ``standard_full`` decision.
"""

from __future__ import annotations

from edgar_sec.domain.forms.common.decisions import DecisionAction, EvaluatorDecision

#: Raw HTML payload length above which a quarterly report is assumed complete.
HTML_SIZE_CEILING = 750_000

#: Raw ASCII payload length above which a quarterly report is assumed complete.
ASCII_SIZE_CEILING = 300_000


def evaluate_quarterly(
    text: str,
    *,
    filing_year: int | str | None = None,
    raw_length: int | None = None,
    is_html: bool = False,
) -> EvaluatorDecision:
    """Decide how a Form 10-Q should be triaged.

    ``filing_year`` and ``raw_length`` enable fast shortcuts when metadata is
    available. ``raw_length`` evaluates raw payload size against
    ``HTML_SIZE_CEILING`` or ``ASCII_SIZE_CEILING`` depending on ``is_html``.

    All three default to the "not supplied" state, because the shared evaluator
    contract is callable with the normalized text alone. The declared defaults
    are the no-shortcut path, so an unsupplied argument can never accidentally
    satisfy a threshold.
    """
    _ = text

    if filing_year is not None and int(filing_year) >= 2012:
        return EvaluatorDecision(
            action=DecisionAction.PROCEED,
            target_exhibit=None,
            reason="Post-2011 XBRL mandate: guaranteed self-contained quarterly filing.",
            is_stub=False,
            category="post_2011_xbrl_full",
            confidence=1.0,
        )

    if raw_length is not None:
        ceiling = HTML_SIZE_CEILING if is_html else ASCII_SIZE_CEILING
        if raw_length > ceiling:
            return EvaluatorDecision(
                action=DecisionAction.PROCEED,
                target_exhibit=None,
                reason="Above size ceiling: self-contained quarterly payload.",
                is_stub=False,
                category="size_ceiling_full",
                confidence=1.0,
            )

    return EvaluatorDecision(
        action=DecisionAction.PROCEED,
        target_exhibit=None,
        reason="Form 10-Q candidate evaluated; proceeding with primary payload.",
        is_stub=False,
        category="standard_full",
        confidence=1.0,
    )


__all__ = [
    "ASCII_SIZE_CEILING",
    "HTML_SIZE_CEILING",
    "evaluate_quarterly",
]
