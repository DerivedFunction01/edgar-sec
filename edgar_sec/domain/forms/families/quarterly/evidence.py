"""Quarterly report evidence definitions and semantic anchors."""

from __future__ import annotations

from dataclasses import dataclass, field

from edgar_sec.domain.forms.common.forward_looking import FORWARD_LOOKING_TERMS
from edgar_sec.domain.forms.common.rules import COMMON_SHARES_RULES
from edgar_sec.domain.forms.common.vocabulary import COMMON_SHARES_PHRASES
from edgar_sec.foundation.text.automaton import CaseMode
from edgar_sec.foundation.text.evidence import EvidenceTier, LexicalEvidencePack
from edgar_sec.foundation.text.healing import PhraseSequenceRule

QUARTERLY_REPORT_TITLES: tuple[str, ...] = (
    "quarterly report pursuant to section 13 or 15(d) of the securities exchange act of 1934",
    "quarterly report pursuant to section 13 or 15(d)",
    "quarterly report under section 13",
    "transition report pursuant to section 13 or 15(d)",
    "for the quarterly period ended",
    "for the transition period from",
)

QUARTERLY_BODY_PHRASES: tuple[str, ...] = (
    "three months ended",
    "six months ended",
    "nine months ended",
    "condensed consolidated balance sheets",
    "condensed consolidated statements of operations",
    "condensed consolidated statements of cash flows",
    "notes to condensed consolidated financial statements",
    "cash and cash equivalents",
    "liquidity and capital resources",
)

QUARTERLY_BODY_STRONG_TERMS: tuple[str, ...] = (
    "sequential",
    "comparable",
    "interim",
    "diluted",
    "amortization",
    "segment",
    "margins",
    "inventories",
    "depreciation",
)

QUARTERLY_BODY_WEAK_TERMS: tuple[str, ...] = (
    "increased",
    "decreased",
    "compared",
    "offset",
    "primarily",
)

QUARTERLY_COVER_EXCLUSION_TERMS: tuple[str, ...] = (
    "quarter",
    "quarterly",
    "pursuant",
    "period",
    "ended",
    "section",
    "form",
    "registrant",
    "commission",
    "report",
    "issuer",
    "herein",
    "thereof",
    "such",
)

QUARTERLY_BODY_LEXICAL_PACK = LexicalEvidencePack(
    name="quarterly_body_start",
    tiers=(
        EvidenceTier(
            name="body_phrase",
            priority=30,
            value=3,
            terms=QUARTERLY_BODY_PHRASES,
            match_kind="ngram",
            min_distinct_hits=1,
        ),
        EvidenceTier(
            name="body_strong",
            priority=20,
            value=2,
            terms=QUARTERLY_BODY_STRONG_TERMS,
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
            terms=QUARTERLY_BODY_WEAK_TERMS,
            match_kind="unigram",
            min_distinct_hits=2,
        ),
    ),
    exclusion_terms=QUARTERLY_COVER_EXCLUSION_TERMS,
)


@dataclass(frozen=True, slots=True)
class QuarterlyReportEvidence:
    """Evidence specific to quarterly reports."""

    shape_terms: tuple[str, ...] = COMMON_SHARES_PHRASES
    healing_rules: list[PhraseSequenceRule] = field(
        default_factory=lambda: list(COMMON_SHARES_RULES)
    )
    body_ngrams: tuple[str, ...] = QUARTERLY_BODY_PHRASES
    body_verbs: tuple[str, ...] = QUARTERLY_BODY_WEAK_TERMS
    body_terms: tuple[str, ...] = QUARTERLY_BODY_STRONG_TERMS
    cover_terms: tuple[str, ...] = QUARTERLY_COVER_EXCLUSION_TERMS
    body_lexical: LexicalEvidencePack = QUARTERLY_BODY_LEXICAL_PACK


__all__ = [
    "QUARTERLY_BODY_LEXICAL_PACK",
    "QUARTERLY_BODY_PHRASES",
    "QUARTERLY_BODY_STRONG_TERMS",
    "QUARTERLY_BODY_WEAK_TERMS",
    "QUARTERLY_COVER_EXCLUSION_TERMS",
    "QUARTERLY_REPORT_TITLES",
    "QuarterlyReportEvidence",
]
