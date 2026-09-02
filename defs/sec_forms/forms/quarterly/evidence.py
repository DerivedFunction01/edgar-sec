"""Quarterly report evidence definitions and semantic anchors."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class QuarterlyReportEvidence:
    """Evidence specific to quarterly reports."""

    cover_end_signals: tuple[str, ...] = (
        "table of contents",
        "part i",
        "item 1",
    )
    body_ngrams: tuple[str, ...] = (
        "quarter",
        "quarterly",
        "sequential",
        "comparable",
    )
    body_verbs: tuple[str, ...] = (
        "decreased",
        "increased",
        "compared",
    )


__all__ = ["QuarterlyReportEvidence"]
