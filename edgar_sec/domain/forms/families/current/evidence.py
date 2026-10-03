"""Current report (8-K, 6-K) evidence definitions and semantic anchors."""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.domain.forms.common.forward_looking import FORWARD_LOOKING_TERMS
from edgar_sec.foundation.text.automaton import CaseMode
from edgar_sec.foundation.text.evidence import EvidenceTier, LexicalEvidencePack

CURRENT_TITLES: tuple[str, ...] = (
    "current report pursuant to section 13 or 15(d) of the securities exchange act of 1934",
    "current report pursuant to section 13 or 15(d)",
    "date of report",
    "date of earliest event reported",
)

CURRENT_BODY_PHRASES: tuple[str, ...] = (
    "material definitive agreement",
    "credit agreement",
    "board of directors",
    "chief executive officer",
    "press release",
    "press release dated",
    "securities exchange act",
    "financial statements and exhibits",
    "effective immediately",
    "revolving credit facility",
    "unaudited pro forma",
    "pro forma condensed",
    "departure of directors",
    "election of directors",
    "regulation fd disclosure",
    "operations and financial condition",
    "submission of matters to a vote of security holders",
)

CURRENT_BODY_STRONG_TERMS: tuple[str, ...] = (
    "agreement",
    "appointed",
    "resigned",
    "elected",
    "terminated",
    "amendment",
    "transaction",
    "merger",
    "acquisition",
    "facility",
    "closing",
    "severance",
    "indemnification",
    "unsecured",
    "underwriting",
    "promissory",
)

CURRENT_BODY_WEAK_TERMS: tuple[str, ...] = (
    "entered",
    "effective",
    "common",
    "shares",
    "stock",
    "corporation",
    "company",
)

CURRENT_COVER_EXCLUSION_TERMS: tuple[str, ...] = (
    "current",
    "report",
    "pursuant",
    "section",
    "form",
    "registrant",
    "commission",
    "earliest",
    "event",
    "herein",
    "thereof",
    "such",
    "securities",
    "exchange",
    "act",
    "incorporation",
    "address",
    "telephone",
)

# An 8-K/6-K body is item-structured prose, so its phrase tier carries the same value as the
# strong unigram tier: neither a lone "material definitive agreement" nor two event nouns
# reaches the three-point strength the annual pack reserves for business prose.
CURRENT_BODY_LEXICAL_PACK = LexicalEvidencePack(
    name="current_body_start",
    tiers=(
        EvidenceTier(
            name="body_phrases",
            priority=30,
            value=2,
            terms=CURRENT_BODY_PHRASES,
            match_kind="ngram",
            min_distinct_hits=1,
        ),
        EvidenceTier(
            name="body_strong",
            priority=20,
            value=2,
            terms=CURRENT_BODY_STRONG_TERMS,
            match_kind="unigram",
            min_distinct_hits=2,
        ),
        EvidenceTier(
            name="body_forward",
            priority=20,
            value=2,
            terms=FORWARD_LOOKING_TERMS,
            match_kind="unigram",
            case_mode=CaseMode.LOWERCASE,
            min_distinct_hits=2,
        ),
        EvidenceTier(
            name="body_weak",
            priority=10,
            value=1,
            terms=CURRENT_BODY_WEAK_TERMS,
            match_kind="unigram",
            min_distinct_hits=2,
        ),
    ),
    exclusion_terms=CURRENT_COVER_EXCLUSION_TERMS,
)


@dataclass(frozen=True, slots=True)
class CurrentReportEvidence:
    """Evidence specific to current reports (8-K, 6-K)."""

    body_ngrams: tuple[str, ...] = CURRENT_BODY_PHRASES
    body_verbs: tuple[str, ...] = CURRENT_BODY_STRONG_TERMS
    body_terms: tuple[str, ...] = CURRENT_BODY_WEAK_TERMS
    cover_terms: tuple[str, ...] = CURRENT_COVER_EXCLUSION_TERMS
    body_lexical: LexicalEvidencePack = CURRENT_BODY_LEXICAL_PACK


__all__ = [
    "CURRENT_BODY_LEXICAL_PACK",
    "CURRENT_BODY_PHRASES",
    "CURRENT_BODY_STRONG_TERMS",
    "CURRENT_BODY_WEAK_TERMS",
    "CURRENT_COVER_EXCLUSION_TERMS",
    "CURRENT_TITLES",
    "CurrentReportEvidence",
]
