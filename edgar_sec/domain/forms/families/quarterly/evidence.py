"""Quarterly report evidence definitions and semantic anchors."""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.foundation.text.evidence import EvidenceTier, LexicalEvidencePack

QUARTERLY_BODY_STRONG_TERMS: tuple[str, ...] = (
    "quarter",
    "quarterly",
    "sequential",
    "comparable",
)

QUARTERLY_BODY_WEAK_TERMS: tuple[str, ...] = (
    "decreased",
    "increased",
    "compared",
)


# A quarterly body carries no decisive phrase tier: comparative reporting
# vocabulary is all the family owns, so the pack scores strong terms first and
# falls back to the weak comparative verbs.
QUARTERLY_BODY_LEXICAL_PACK = LexicalEvidencePack(
    name="quarterly_body_start",
    tiers=(
        EvidenceTier(
            name="body_strong",
            priority=20,
            value=2,
            terms=QUARTERLY_BODY_STRONG_TERMS,
            match_kind="unigram",
            min_distinct_hits=2,
        ),
        EvidenceTier(
            name="body_weak",
            priority=10,
            value=1,
            terms=QUARTERLY_BODY_WEAK_TERMS,
            match_kind="unigram",
            min_distinct_hits=2,
        ),
    ),
)


@dataclass(frozen=True, slots=True)
class QuarterlyReportEvidence:
    """Evidence specific to quarterly reports."""

    cover_end_signals: tuple[str, ...] = (
        "table of contents",
        "part i",
        "item 1",
    )
    body_ngrams: tuple[str, ...] = QUARTERLY_BODY_STRONG_TERMS
    body_verbs: tuple[str, ...] = QUARTERLY_BODY_WEAK_TERMS
    body_lexical: LexicalEvidencePack = QUARTERLY_BODY_LEXICAL_PACK


__all__ = [
    "QUARTERLY_BODY_LEXICAL_PACK",
    "QUARTERLY_BODY_STRONG_TERMS",
    "QUARTERLY_BODY_WEAK_TERMS",
    "QuarterlyReportEvidence",
]
