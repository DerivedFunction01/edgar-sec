"""Quarterly report (Form 10-Q) stub and refetch evaluator.

A 10-Q carries its financial statements inline under the same regime as the
10-K, so this evaluator is a set of cheap early exits rather than a
content-analysis pass: post-2011 filings and oversized payloads are provably
self-contained, and anything that reaches the content tier proceeds with the
primary payload.
"""

from __future__ import annotations

from edgar_sec.domain.forms.decisions import EvaluatorDecision
from edgar_sec.engine.forms.evaluators.base import (
    EvaluatorInput,
    proceed,
)


def evaluate_quarterly(payload: str | EvaluatorInput) -> EvaluatorDecision:
    """Evaluate a quarterly report for stub content requiring a second fetch."""
    data = EvaluatorInput.coerce(payload)

    # Tier 1: post-2011 XBRL mandate bypass.
    if data.is_post_xbrl:
        return proceed(
            "Post-2011 XBRL mandate: guaranteed self-contained quarterly filing.",
            "post_2011_xbrl_full",
        )

    # Tier 2: format and size ceiling bypass (HTML > 750KB, TXT > 300KB).
    if data.above_size_ceiling:
        return proceed(
            "Above size ceiling: self-contained quarterly payload.",
            "size_ceiling_full",
        )

    # Tier 3: pre-2011 candidate evaluation. A 10-Q has no incorporation-stub
    # structure in the corpus, so there is no exhibit to refetch.
    return proceed(
        "Form 10-Q candidate evaluated; proceeding with primary payload.",
        "standard_full",
    )


__all__ = ["evaluate_quarterly"]
