"""Ownership report family evidence definitions, lexical packs, and vetoes."""

from __future__ import annotations

from edgar_sec.foundation.text.evidence import EvidenceTier, LexicalEvidencePack

FOOTNOTE_DECISIVE_PHRASES: tuple[str, ...] = (
    "explanation of responses",
    "footnote description",
    "footnote descriptions",
    "restricted stock units",
    "restricted stock",
    "vesting schedule",
    "shares withheld to satisfy",
    "subject to forfeiture",
    "deferred compensation",
    "automatic reinvestment",
    "power of attorney",
    "weighted average",
)

FOOTNOTE_STRONG_VERBS: tuple[str, ...] = (
    "vesting",
    "vest",
    "vests",
    "forfeiture",
    "withheld",
    "settled",
    "installments",
    "exercisable",
    "pursuant",
    "reinvestment",
    "satisfy",
)

FOOTNOTE_SUPPORT_TERMS: tuple[str, ...] = (
    "grant",
    "units",
    "plan",
    "compensation",
    "deferred",
    "incentive",
    "dividend",
    "stock",
    "common",
)

FOOTNOTE_EXCLUSION_TERMS: tuple[str, ...] = (
    "ticker",
    "irs",
)

FOOTNOTE_VETO_PHRASES: tuple[str, ...] = (
    "name and address of reporting person",
    "issuer name and ticker",
    "table i",
    "table ii",
    "non-derivative",
    "title of security",
    "title of derivative",
    "signature of reporting person",
)

OWNERSHIP_FOOTNOTE_LEXICAL_PACK = LexicalEvidencePack(
    name="ownership_footnote",
    tiers=(
        EvidenceTier(
            name="footnote_decisive",
            priority=30,
            value=3,
            terms=FOOTNOTE_DECISIVE_PHRASES,
            match_kind="ngram",
            min_distinct_hits=1,
        ),
        EvidenceTier(
            name="footnote_strong",
            priority=20,
            value=2,
            terms=FOOTNOTE_STRONG_VERBS,
            match_kind="unigram",
            min_distinct_hits=2,
        ),
        EvidenceTier(
            name="footnote_support",
            priority=10,
            value=1,
            terms=FOOTNOTE_SUPPORT_TERMS,
            match_kind="unigram",
            min_distinct_hits=2,
            support=True,
        ),
    ),
    exclusion_terms=FOOTNOTE_EXCLUSION_TERMS,
)

__all__ = [
    "FOOTNOTE_DECISIVE_PHRASES",
    "FOOTNOTE_EXCLUSION_TERMS",
    "FOOTNOTE_STRONG_VERBS",
    "FOOTNOTE_SUPPORT_TERMS",
    "FOOTNOTE_VETO_PHRASES",
    "OWNERSHIP_FOOTNOTE_LEXICAL_PACK",
]
