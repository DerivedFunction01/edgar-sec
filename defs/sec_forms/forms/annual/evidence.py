"""Annual report evidence definitions and semantic anchors."""

from __future__ import annotations

from dataclasses import dataclass, field

from defs.sec_forms.forms.annual.sequences import ANNUAL_ADDITIONAL_PHRASE_RULES
from defs.sec_forms.forms.annual.vocabulary import (
    INCORPORATED_REFERENCE_TERMS,
    PUBLIC_FLOAT_PHRASES,
    SHARES_PHRASES,
)
from defs.text import EvidenceTier, LexicalEvidencePack, PhraseSequenceRule

# High-confidence annual body phrases: one distinct phrase hit is decisive.
ANNUAL_BODY_PHRASES: tuple[str, ...] = (
    "collective bargaining",
    "labor union",
    "market segments",
)

# Curated high-confidence early-body unigrams. Two distinct terms clear the
# strong tier; the two-term minimum reflects that the probe vocabulary was
# sampled, not observed across the full filing corpus.
ANNUAL_BODY_STRONG_TERMS: tuple[str, ...] = (
    "founded",
    "organized",
    "leading",
    "provider",
    "primarily",
    "overview",
    "engaged",
    "operated",
    "located",
    "manufacturing",
    "worldwide",
    "segments",
    "commenced",
    "began",
    "manufacturer",
    "range",
    "focus",
    "focused",
    "specialty",
    "headquartered",
    "subsidiaries",
    "acquired",
    "employees",
    "customers",
    "suppliers",
    "facilities",
    "competition",
)

ANNUAL_BODY_VERBS: tuple[str, ...] = (
    "provides",
    "operates",
    "manufactures",
    "sells",
    "develops",
    "distributes",
    "manages",
    "expects",
    "believes",
    "anticipates",
)

# Weaker body-leaning vocabulary: two distinct terms are required to count.
ANNUAL_BODY_WEAK_TERMS: tuple[str, ...] = (
    *ANNUAL_BODY_VERBS,
    "products",
    "services",
    "operations",
    "sales",
    "revenue",
    "fiscal",
    "approximately",
    "markets",
    "industry",
    "network",
)

# Cover/form-leaning terms recorded as exclusions. They are reported on the
# score result and never reduce or veto a lexical score by themselves.
ANNUAL_COVER_EXCLUSION_TERMS: tuple[str, ...] = (
    "pursuant",
    "herein",
    "hereof",
    "hereunder",
    "thereof",
    "therein",
    "thereto",
    "whereby",
    "including",
    "other",
    "its",
    "any",
    "has",
    "is",
    "was",
    "been",
    "such",
    "all",
    "will",
    "whether",
    "preceding",
    "commission",
    "registrant",
    "filer",
    "form",
)

ANNUAL_BODY_LEXICAL_PACK = LexicalEvidencePack(
    name="annual_body_start",
    tiers=(
        EvidenceTier(
            name="body_phrase",
            priority=30,
            value=3,
            terms=ANNUAL_BODY_PHRASES,
            match_kind="ngram",
            min_distinct_hits=1,
        ),
        EvidenceTier(
            name="body_strong",
            priority=20,
            value=2,
            terms=ANNUAL_BODY_STRONG_TERMS,
            match_kind="unigram",
            min_distinct_hits=2,
        ),
        EvidenceTier(
            name="body_weak",
            priority=10,
            value=1,
            terms=ANNUAL_BODY_WEAK_TERMS,
            match_kind="unigram",
            min_distinct_hits=2,
        ),
    ),
    exclusion_terms=ANNUAL_COVER_EXCLUSION_TERMS,
)


@dataclass(frozen=True, slots=True)
class AnnualReportEvidence:
    """Evidence specific to annual and foreign annual reports."""

    incorporated_reference_terms: tuple[str, ...] = INCORPORATED_REFERENCE_TERMS
    cover_end_signals: tuple[str, ...] = (
        "table of contents",
        "part i",
        "item 1",
    )
    shape_terms: tuple[str, ...] = (
        *PUBLIC_FLOAT_PHRASES,
        *SHARES_PHRASES,
    )
    body_ngrams: tuple[str, ...] = (
        *ANNUAL_BODY_PHRASES,
        "worldwide",
        "employees",
        "customers",
        "suppliers",
        "facilities",
        "competition",
    )
    body_verbs: tuple[str, ...] = ANNUAL_BODY_VERBS
    body_terms: tuple[str, ...] = (
        *ANNUAL_BODY_STRONG_TERMS,
        "products",
        "services",
        "operations",
        "sales",
        "revenue",
        "fiscal",
        "approximately",
    )
    cover_terms: tuple[str, ...] = ANNUAL_COVER_EXCLUSION_TERMS
    body_lexical: LexicalEvidencePack = ANNUAL_BODY_LEXICAL_PACK
    semantic_headings: tuple[str, ...] = (
        "management's discussion and analysis",
        "risk factors",
        "forward-looking statements",
        "safe harbor",
        "quantitative and qualitative disclosures",
        "properties",
        "legal proceedings",
        "market for registrant's common equity",
        "selected financial data",
        "changes in and disagreements with accountants",
        "controls and procedures",
        "directors, executive officers",
        "executive compensation",
        "security ownership",
        "certain relationships",
        "principal accountant fees",
        "exhibit and financial statement schedules",
    )
    healing_rules: tuple[PhraseSequenceRule, ...] = field(
        default_factory=lambda: tuple(ANNUAL_ADDITIONAL_PHRASE_RULES)
    )


__all__ = [
    "ANNUAL_BODY_LEXICAL_PACK",
    "ANNUAL_BODY_PHRASES",
    "ANNUAL_BODY_STRONG_TERMS",
    "ANNUAL_BODY_VERBS",
    "ANNUAL_BODY_WEAK_TERMS",
    "ANNUAL_COVER_EXCLUSION_TERMS",
    "AnnualReportEvidence",
]
