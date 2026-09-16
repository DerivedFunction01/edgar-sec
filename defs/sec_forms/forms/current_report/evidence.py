"""Current report (8-K, 6-K) evidence definitions and semantic anchors."""

from __future__ import annotations

from dataclasses import dataclass

from defs.text import EvidenceTier, LexicalEvidencePack

CURRENT_REPORT_BODY_PHRASES: tuple[str, ...] = (
    "material definitive agreement",
    "credit agreement",
    "board of directors",
    "chief executive officer",
    "press release",
    "forward-looking statements",
    "forward looking statements",
    "securities exchange act",
    "financial statements and exhibits",
    "effective immediately",
    "revolving credit facility",
)

CURRENT_REPORT_BODY_STRONG_TERMS: tuple[str, ...] = (
    "agreement",
    "pursuant",
    "appointed",
    "resigned",
    "amendment",
    "transaction",
    "merger",
    "acquisition",
    "facility",
    "operations",
    "registrant",
    "exhibit",
    "exhibits",
    "director",
    "officer",
    "closing",
)

CURRENT_REPORT_BODY_WEAK_TERMS: tuple[str, ...] = (
    "entered",
    "effective",
    "common",
    "shares",
    "stock",
    "corporation",
    "company",
)

CURRENT_REPORT_BODY_LEXICAL_PACK = LexicalEvidencePack(
    name="current_report_body_start",
    tiers=(
        EvidenceTier(
            name="body_phrases",
            priority=30,
            value=2,
            terms=CURRENT_REPORT_BODY_PHRASES,
            match_kind="ngram",
            min_distinct_hits=1,
        ),
        EvidenceTier(
            name="body_strong",
            priority=20,
            value=2,
            terms=CURRENT_REPORT_BODY_STRONG_TERMS,
            match_kind="unigram",
            min_distinct_hits=2,
        ),
        EvidenceTier(
            name="body_weak",
            priority=10,
            value=1,
            terms=CURRENT_REPORT_BODY_WEAK_TERMS,
            match_kind="unigram",
            min_distinct_hits=2,
        ),
    ),
)


@dataclass(frozen=True, slots=True)
class CurrentReportEvidence:
    """Evidence specific to current reports (8-K, 6-K)."""

    body_ngrams: tuple[str, ...] = CURRENT_REPORT_BODY_PHRASES
    body_verbs: tuple[str, ...] = CURRENT_REPORT_BODY_STRONG_TERMS
    body_terms: tuple[str, ...] = CURRENT_REPORT_BODY_WEAK_TERMS
    body_lexical: LexicalEvidencePack = CURRENT_REPORT_BODY_LEXICAL_PACK


__all__ = [
    "CURRENT_REPORT_BODY_LEXICAL_PACK",
    "CURRENT_REPORT_BODY_PHRASES",
    "CURRENT_REPORT_BODY_STRONG_TERMS",
    "CURRENT_REPORT_BODY_WEAK_TERMS",
    "CurrentReportEvidence",
]
