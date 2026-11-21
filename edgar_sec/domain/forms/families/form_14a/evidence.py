"""Schedule 14A evidence definitions and semantic anchors."""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.domain.forms.common.forward_looking import FORWARD_LOOKING_TERMS
from edgar_sec.domain.forms.common.vocabulary import COMMON_COVER_EXCLUSION_TERMS
from edgar_sec.foundation.text.automaton import CaseMode
from edgar_sec.foundation.text.evidence import EvidenceTier, LexicalEvidencePack

FORM_14A_BODY_PHRASES: tuple[str, ...] = (
    "notice of annual meeting",
    "notice of special meeting",
    "annual meeting of stockholders",
    "special meeting of stockholders",
    "board of directors",
    "record date",
    "shares outstanding",
    "voting securities",
    "dear stockholder",
    "dear shareholder",
    "by order of the board",
    "election of directors",
    "executive compensation",
    "shares of common stock",
    "outstanding shares",
    "beneficial owners",
    "beneficial ownership",
    "independent registered public accounting firm",
    "annual meeting",
    "proxy materials",
    "proxy card",
)

FORM_14A_BODY_STRONG_TERMS: tuple[str, ...] = (
    "stockholders",
    "shareholders",
    "proxy",
    "voting",
    "directors",
    "compensation",
    "quorum",
    "ballot",
    "nominees",
    "solicitation",
    "beneficial",
    "outstanding",
    "meeting",
)

FORM_14A_BODY_WEAK_TERMS: tuple[str, ...] = (
    "elect",
    "approve",
    "ratify",
    "appoint",
    "vote",
    "solicit",
    "recommend",
    "authorize",
    "entitle",
    "attend",
)

FORM_14A_COVER_EXCLUSION_TERMS: tuple[str, ...] = (
    *COMMON_COVER_EXCLUSION_TERMS,
    "charter",
    "preliminary",
    "soliciting",
)

FORM_14A_BODY_LEXICAL_PACK = LexicalEvidencePack(
    name="form_14a_body_start",
    tiers=(
        EvidenceTier(
            name="body_phrase",
            priority=30,
            value=3,
            terms=FORM_14A_BODY_PHRASES,
            match_kind="ngram",
            min_distinct_hits=1,
        ),
        EvidenceTier(
            name="body_strong",
            priority=20,
            value=2,
            terms=FORM_14A_BODY_STRONG_TERMS,
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
            terms=FORM_14A_BODY_WEAK_TERMS,
            match_kind="unigram",
            min_distinct_hits=2,
        ),
    ),
    exclusion_terms=FORM_14A_COVER_EXCLUSION_TERMS,
)


@dataclass(frozen=True, slots=True)
class Form14AEvidence:
    """Evidence specific to Schedule 14A/14C statements."""

    body_ngrams: tuple[str, ...] = FORM_14A_BODY_PHRASES
    body_verbs: tuple[str, ...] = FORM_14A_BODY_WEAK_TERMS
    body_terms: tuple[str, ...] = FORM_14A_BODY_STRONG_TERMS
    cover_terms: tuple[str, ...] = FORM_14A_COVER_EXCLUSION_TERMS
    body_lexical: LexicalEvidencePack = FORM_14A_BODY_LEXICAL_PACK


__all__ = [
    "FORM_14A_BODY_LEXICAL_PACK",
    "FORM_14A_BODY_PHRASES",
    "FORM_14A_BODY_STRONG_TERMS",
    "FORM_14A_BODY_WEAK_TERMS",
    "FORM_14A_COVER_EXCLUSION_TERMS",
    "Form14AEvidence",
]
