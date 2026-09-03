"""Annual report evidence definitions and semantic anchors."""

from __future__ import annotations

from dataclasses import dataclass, field

from defs.sec_forms.forms.annual.sequences import ANNUAL_ADDITIONAL_PHRASE_RULES
from defs.sec_forms.forms.annual.vocabulary import (
    INCORPORATED_REFERENCE_TERMS,
    PUBLIC_FLOAT_PHRASES,
    SHARES_PHRASES,
)
from defs.text import CaseMode, EvidenceTier, LexicalEvidencePack, PhraseSequenceRule

# Decisive annual body phrases: one distinct phrase hit confirms body prose.
# Membership requires zero observed cover-only false positives in the corpus
# probe; phrases with any cover collision belong in ANNUAL_BODY_SOFT_PHRASES.
ANNUAL_BODY_PHRASES: tuple[str, ...] = (
    "collective bargaining",
    "labor union",
    "market segments",
    "management believes",
    "future cash flows",
    "assumptions and estimates",
)

# Corroborating body phrases with observed cover-prefix collision (cover quotes
# of forward-looking boilerplate, TOC/notice text). One hit contributes support
# evidence (additive value 1) and can confirm body start only alongside other
# word evidence; a soft phrase alone never clears the decision threshold.
ANNUAL_BODY_SOFT_PHRASES: tuple[str, ...] = (
    "safe harbor",
    "cautionary statements",
    "undue reliance",
    "statements include",
    "future performance",
    "unless the context",
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

# Forward-looking vocabulary from the combined BoW classifier.
# "may" must be lowercase to avoid matching the month name "May".
# "future" is intentionally absent: the fold-mode "future performance" phrase
# now owns that token shape, and case modes cannot share a token per pack.
ANNUAL_BODY_FORWARD_TERMS: tuple[str, ...] = (
    "forward",
    "looking",
    "actual",
    "results",
    "materially",
    "risks",
    "differ",
    "uncertainties",
    "believe",
    "expect",
    "anticipate",
    "estimate",
    "intend",
    "following",
    "certain",
    "may",
)

# ITEM 1 header text vocabulary from the combined BoW classifier.
ANNUAL_BODY_HEADER_TERMS: tuple[str, ...] = (
    "business",
    "description",
    "operations",
    "general",
    "overview",
)

ANNUAL_BODY_HEADER_PHRASES: tuple[str, ...] = ("our company",)

# General body-leaning vocabulary from the combined BoW classifier.
ANNUAL_BODY_GENERAL_TERMS: tuple[str, ...] = (
    "continue",
    "include",
    "their",
    "regarding",
    "could",
    "should",
    "plan",
    "had",
    "have",
    "approximately",
    "were",
    "are",
    "each",
    "which",
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
            name="body_forward",
            priority=20,
            value=2,
            terms=ANNUAL_BODY_FORWARD_TERMS,
            match_kind="unigram",
            case_mode=CaseMode.LOWERCASE,
            min_distinct_hits=2,
        ),
        EvidenceTier(
            name="body_header",
            priority=20,
            value=2,
            terms=ANNUAL_BODY_HEADER_TERMS,
            match_kind="unigram",
            min_distinct_hits=2,
        ),
        EvidenceTier(
            name="body_header_phrase",
            priority=20,
            value=2,
            terms=ANNUAL_BODY_HEADER_PHRASES,
            match_kind="ngram",
            min_distinct_hits=1,
        ),
        EvidenceTier(
            name="body_phrase_soft",
            priority=15,
            value=1,
            terms=ANNUAL_BODY_SOFT_PHRASES,
            match_kind="ngram",
            min_distinct_hits=1,
            support=True,
        ),
        EvidenceTier(
            name="body_general",
            priority=10,
            value=1,
            terms=ANNUAL_BODY_GENERAL_TERMS,
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
    forward_terms: tuple[str, ...] = ANNUAL_BODY_FORWARD_TERMS
    header_terms: tuple[str, ...] = ANNUAL_BODY_HEADER_TERMS
    header_phrases: tuple[str, ...] = ANNUAL_BODY_HEADER_PHRASES
    soft_phrases: tuple[str, ...] = ANNUAL_BODY_SOFT_PHRASES
    general_terms: tuple[str, ...] = ANNUAL_BODY_GENERAL_TERMS
    semantic_headings: tuple[str, ...] = (
        "management's discussion and analysis",
        "risk factors",
        "forward-looking statements",
        "forward looking statements",
        "forward looking information",
        "forward-looking information",
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
    "ANNUAL_BODY_FORWARD_TERMS",
    "ANNUAL_BODY_GENERAL_TERMS",
    "ANNUAL_BODY_HEADER_PHRASES",
    "ANNUAL_BODY_HEADER_TERMS",
    "ANNUAL_BODY_LEXICAL_PACK",
    "ANNUAL_BODY_PHRASES",
    "ANNUAL_BODY_SOFT_PHRASES",
    "ANNUAL_BODY_STRONG_TERMS",
    "ANNUAL_BODY_VERBS",
    "ANNUAL_BODY_WEAK_TERMS",
    "ANNUAL_COVER_EXCLUSION_TERMS",
    "AnnualReportEvidence",
]
