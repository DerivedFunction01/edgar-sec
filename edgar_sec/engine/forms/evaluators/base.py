"""Shared input record and helpers for form stub/delegation evaluators.

An evaluator decides whether a fetched primary document is a self-contained
filing or a stub that delegates substantive disclosure to an exhibit. The
decision drives a second, targeted fetch pass, so an evaluator must be cheap:
it reads only what it needs and returns a decision with a reproducible reason.
"""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.domain.forms.decisions import DecisionAction, EvaluatorDecision

#: First filing year under the mandatory XBRL regime. Filings from this year on
#: carry their financial statements inline and cannot be incorporation stubs.
XBRL_MANDATE_YEAR = 2012

#: Size ceilings above which a payload is assumed self-contained. HTML filings
#: run several times larger than ASCII ones for the same content.
HTML_SIZE_CEILING = 750_000
ASCII_SIZE_CEILING = 300_000


@dataclass(frozen=True, slots=True)
class EvaluatorInput:
    """What an evaluator is allowed to look at."""

    text: str
    raw_text: str = ""
    has_html_tags: bool = False
    filing_year: int | None = None

    @classmethod
    def coerce(cls, payload: str | EvaluatorInput) -> EvaluatorInput:
        """Accept a bare text payload, treating it as the cleaned text."""
        if isinstance(payload, EvaluatorInput):
            return payload
        return cls(text=payload, raw_text=payload)

    @property
    def body_text(self) -> str:
        return self.text or self.raw_text

    @property
    def is_post_xbrl(self) -> bool:
        return (
            self.filing_year is not None and int(self.filing_year) >= XBRL_MANDATE_YEAR
        )

    @property
    def above_size_ceiling(self) -> bool:
        raw_len = len(self.raw_text or self.text)
        if self.has_html_tags:
            return raw_len > HTML_SIZE_CEILING
        return raw_len > ASCII_SIZE_CEILING


def proceed(reason: str, category: str, confidence: float = 1.0) -> EvaluatorDecision:
    """Build a ``PROCEED`` decision."""
    return EvaluatorDecision(
        action=DecisionAction.PROCEED,
        target_exhibit=None,
        reason=reason,
        is_stub=False,
        category=category,
        confidence=confidence,
    )


def refetch_exhibit(
    exhibit: str,
    reason: str,
    category: str,
    **metadata: object,
) -> EvaluatorDecision:
    """Build a ``REFETCH_SUB_DOC`` decision targeting ``exhibit``."""
    return EvaluatorDecision(
        action=DecisionAction.REFETCH_SUB_DOC,
        target_exhibit=exhibit,
        reason=reason,
        is_stub=True,
        category=category,
        confidence=1.0,
        metadata=dict(metadata),
    )


__all__ = [
    "ASCII_SIZE_CEILING",
    "HTML_SIZE_CEILING",
    "XBRL_MANDATE_YEAR",
    "EvaluatorInput",
    "proceed",
    "refetch_exhibit",
]
