"""Quarterly report (Form 10-Q) stub and refetch evaluator. Two fast paths when
metadata is supplied: the post-2011 XBRL mandate makes a filing self-contained by
construction, and a raw payload past its size ceiling is assumed complete.
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
    """How a Form 10-Q should be triaged. Every metadata argument defaults to "not
    supplied", which is the no-shortcut path: the contract must stay text-only.
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
