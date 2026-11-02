"""Form 11-K evidence definitions and semantic anchors."""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.domain.forms.common.vocabulary import COMMON_COVER_EXCLUSION_TERMS
from edgar_sec.foundation.text.evidence import EvidenceTier, LexicalEvidencePack

FORM_11K_BODY_PHRASES: tuple[str, ...] = (
    "statements of net assets available for benefits",
    "statement of net assets available for benefits",
    "statements of changes in net assets available for benefits",
    "statement of changes in net assets available for benefits",
    "report of independent registered public accounting firm",
    "notes to financial statements",
    "financial statements and supplemental schedules",
    "net assets available for benefits",
)

FORM_11K_BODY_STRONG_TERMS: tuple[str, ...] = (
    "financial",
    "statements",
    "assets",
    "benefits",
    "supplemental",
    "schedules",
    "audited",
    "participants",
    "contributions",
    "investments",
)

FORM_11K_BODY_WEAK_TERMS: tuple[str, ...] = (
    "audited",
    "presents",
    "administered",
    "accordance",
    "opinion",
    "examined",
)

FORM_11K_COVER_EXCLUSION_TERMS: tuple[str, ...] = COMMON_COVER_EXCLUSION_TERMS

FORM_11K_BODY_LEXICAL_PACK = LexicalEvidencePack(
    name="form_11k_body_start",
    tiers=(
        EvidenceTier(
            name="body_phrase",
            priority=30,
            value=3,
            terms=FORM_11K_BODY_PHRASES,
            match_kind="ngram",
            min_distinct_hits=1,
        ),
        EvidenceTier(
            name="body_strong",
            priority=20,
            value=2,
            terms=FORM_11K_BODY_STRONG_TERMS,
            match_kind="unigram",
            min_distinct_hits=2,
        ),
        EvidenceTier(
            name="body_weak",
            priority=10,
            value=1,
            terms=FORM_11K_BODY_WEAK_TERMS,
            match_kind="unigram",
            min_distinct_hits=2,
        ),
    ),
    exclusion_terms=FORM_11K_COVER_EXCLUSION_TERMS,
)


@dataclass(frozen=True, slots=True)
class Form11KEvidence:
    """Evidence specific to Form 11-K plan annual reports."""

    body_ngrams: tuple[str, ...] = FORM_11K_BODY_PHRASES
    body_verbs: tuple[str, ...] = FORM_11K_BODY_WEAK_TERMS
    body_terms: tuple[str, ...] = FORM_11K_BODY_STRONG_TERMS
    cover_terms: tuple[str, ...] = FORM_11K_COVER_EXCLUSION_TERMS
    body_lexical: LexicalEvidencePack = FORM_11K_BODY_LEXICAL_PACK


__all__ = [
    "FORM_11K_BODY_LEXICAL_PACK",
    "FORM_11K_BODY_PHRASES",
    "FORM_11K_BODY_STRONG_TERMS",
    "FORM_11K_BODY_WEAK_TERMS",
    "FORM_11K_COVER_EXCLUSION_TERMS",
    "Form11KEvidence",
]
