"""Annual report evidence definitions and semantic anchors."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from edgar_sec.domain.forms.common.forward_looking import (
    FORWARD_LOOKING_PHRASES,
    FORWARD_LOOKING_TERMS,
    FORWARD_LOOKING_VERBS,
)
from edgar_sec.foundation.regex.builder import build_alternation
from edgar_sec.foundation.text.automaton import CaseMode
from edgar_sec.foundation.text.evidence import EvidenceTier, LexicalEvidencePack
from edgar_sec.foundation.text.healing import PhraseSequenceRule

INCORPORATED_REFERENCE_TERMS: tuple[str, ...] = (
    "documents incorporated by reference",
    "documents incorporated by reference:",
    "list hereunder the following documents if incorporated by reference",
    "the following documents are incorporated by reference",
)

BANKRUPTCY_PROCEEDINGS_TERMS: tuple[str, ...] = (
    "applicable only to registrants involved in bankruptcy proceedings during the preceding five years",
    "bankruptcy proceedings during the preceding five years",
    "plan confirmed by a court",
)

ANNUAL_TARGET_EXHIBITS: tuple[str, ...] = (
    "EX-13",
    "EX-13.1",
    "EX-13.2",
    "EX-99",
    "EX-99.1",
    "EX-99.2",
    "EX-99.3",
    "EX-2.1",
)

ANNUAL_REPORT_TITLES: tuple[str, ...] = (
    "annual report pursuant to section 13 or 15(d) of the securities exchange act of 1934",
    "annual report pursuant to section 13 or 15(d)",
    "annual report under section 13",
    "transition report pursuant to section 13 or 15(d)",
    "transition report pursuant to section 13",
    "for the fiscal year ended",
    "for the transition period from",
    "index to report",
)

DELINQUENT_FILERS_TERMS: tuple[str, ...] = (
    "pursuant to item 405 of regulation s-k",
    "pursuant to item 405",
    "delinquent filers",
    "disclosure of delinquent filers",
)

PUBLIC_FLOAT_PHRASES: tuple[str, ...] = (
    "state the aggregate market value of the voting and non-voting common equity held by non-affiliates",
    "the aggregate market value of the voting and non-voting common equity held by non-affiliates",
    "aggregate market value of voting and non-voting common equity held by non-affiliates",
    "aggregate market value of the voting and non-voting common equity held by non-affiliates",
    "aggregate market value of the voting and non-voting stock held by non-affiliates",
    "aggregate market value of the common stock held by non-affiliates",
    "aggregate market value of the common equity held by non-affiliates",
    "aggregate market value of voting and non-voting common stock held by non-affiliates",
    "voting and non-voting common equity held by non-affiliates",
    "voting and non-voting common equity",
    "last business day of the registrant's most recently completed second fiscal quarter",
    "most recently completed second fiscal quarter",
    "last business day",
    "aggregate market value",
    "non-affiliates",
)

from edgar_sec.domain.forms.common.rules import COMMON_SHARES_RULES
from edgar_sec.domain.forms.common.vocabulary import COMMON_SHARES_PHRASES

SHARES_PHRASES: tuple[str, ...] = COMMON_SHARES_PHRASES

# Decisive annual body phrases: one distinct hit confirms body prose. Includes the
# audit-opinion and amendment-note phrasing of a 10-K/A, which never appears in
# cover-page boilerplate.
ANNUAL_BODY_PHRASES: tuple[str, ...] = (
    "collective bargaining",
    "labor union",
    "market segments",
    "management believes",
    "future cash flows",
    "assumptions and estimates",
    "we have audited",
    "in our opinion",
    "balance sheets",
    "statements of operations",
    "accounting principles",
    "this amendment is being filed",
    "amendment is being filed",
)

ANNUAL_BODY_SOFT_PHRASES: tuple[str, ...] = (
    "safe harbor",
    "cautionary statements",
    "undue reliance",
    "statements include",
    "future performance",
    "unless the context",
)

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

ANNUAL_BUSINESS_VERBS: tuple[str, ...] = (
    "provides",
    "operates",
    "manufactures",
    "sells",
    "develops",
    "distributes",
    "manages",
)

ANNUAL_BODY_VERBS: tuple[str, ...] = (
    *ANNUAL_BUSINESS_VERBS,
    *FORWARD_LOOKING_VERBS[:5],
)

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

ANNUAL_BODY_FORWARD_TERMS: tuple[str, ...] = FORWARD_LOOKING_TERMS

ANNUAL_BODY_HEADER_TERMS: tuple[str, ...] = (
    "business",
    "description",
    "operations",
    "general",
    "overview",
)

ANNUAL_BODY_HEADER_PHRASES: tuple[str, ...] = ("our company",)

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

# Annual body prose tiers, from decisive phrases down to corroborating soft ones. The
# forward tier matches all-lowercase tokens only, so safe-harbor boilerplate cannot
# score as body prose on its own.
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

PUBLIC_FLOAT_ANCHOR_RE = re.compile(
    build_alternation(
        [PUBLIC_FLOAT_PHRASES[0]], auto_escape=True, flexible_whitespace=True
    ),
    re.IGNORECASE,
)

_FLOAT_UNIT = (
    rf"(?:{build_alternation(['billion', 'million', 'thousand'], auto_escape=True)})?"
)
_FLOAT_VALUE_INNER = (
    rf"\$\s*[\d][\d,.]{{0,15}}\s*{_FLOAT_UNIT}"
    rf"|\b\d[\d,.]{{0,15}}\s*{_FLOAT_UNIT}\s*dollars\b"
)
PUBLIC_FLOAT_VALUE_RE = re.compile(rf"({_FLOAT_VALUE_INNER})", re.IGNORECASE)
PUBLIC_FLOAT_EXACT_RE = re.compile(r"(\$\s*[\d][\d,.]{3,})", re.IGNORECASE)

SHARES_ANCHOR_RE = re.compile(
    build_alternation(
        [SHARES_PHRASES[0], SHARES_PHRASES[1]],
        auto_escape=True,
        flexible_whitespace=True,
    ),
    re.IGNORECASE,
)
SHARES_VALUE_RE = re.compile(
    r"\b(?:\d{1,3}(?:,\d{3})+|\d{5,12})\b\s*(?:shares\b)?", re.IGNORECASE
)

_SHARES_RULES: list[PhraseSequenceRule] = list(COMMON_SHARES_RULES)

_PUBLIC_FLOAT_RULES: list[PhraseSequenceRule] = [
    PhraseSequenceRule(
        name="aggregate_market_value",
        tokens=[
            *PUBLIC_FLOAT_PHRASES[1].split()[:5],
            ["voting", "non-voting"],
            "and",
            ["voting", "non-voting"],
            *PUBLIC_FLOAT_PHRASES[1].split()[8:],
        ],
        anchor=["aggregate market value", "non-affiliates"],
    ),
    PhraseSequenceRule(
        name="held_by_non_affiliates",
        tokens=["held", "by", "non-affiliates", "of", "the", "registrant"],
        anchor=["non-affiliates"],
    ),
]

_DOCUMENTS_INCORPORATED_RULES: list[PhraseSequenceRule] = [
    PhraseSequenceRule(
        name="documents_incorporated_reference",
        tokens=["documents", "incorporated", "by", "reference"],
        anchor=["incorporated by reference"],
    ),
]

_AUDITOR_RULES: list[PhraseSequenceRule] = [
    PhraseSequenceRule(
        name="auditor_firm_id",
        tokens=["auditor", "firm", ["id", "identification", "number"]],
        anchor=["auditor"],
    ),
    PhraseSequenceRule(
        name="auditor_name_location",
        tokens=["auditor", ["name", "location"]],
        anchor=["auditor"],
    ),
]

_EXTENDED_TRANSITION_RULES: list[PhraseSequenceRule] = [
    PhraseSequenceRule(
        name="extended_transition_period",
        tokens=[
            "extended",
            "transition",
            "period",
            "for",
            "complying",
            "with",
            "any",
            "new",
            "or",
            "revised",
            "financial",
            "accounting",
            "standards",
        ],
        anchor=["extended transition", "accounting standards"],
    ),
]

ANNUAL_ADDITIONAL_PHRASE_RULES: list[PhraseSequenceRule] = [
    *_SHARES_RULES,
    *_PUBLIC_FLOAT_RULES,
    *_DOCUMENTS_INCORPORATED_RULES,
    *_AUDITOR_RULES,
    *_EXTENDED_TRANSITION_RULES,
]


@dataclass(frozen=True, slots=True)
class AnnualReportEvidence:
    """Evidence specific to annual and foreign annual reports."""

    incorporated_reference_terms: tuple[str, ...] = INCORPORATED_REFERENCE_TERMS
    shape_terms: tuple[str, ...] = (
        *PUBLIC_FLOAT_PHRASES,
        *SHARES_PHRASES,
        *BANKRUPTCY_PROCEEDINGS_TERMS,
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
        *FORWARD_LOOKING_PHRASES,
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
        # Amendment-specific semantic anchors: these head sections that immediately
        # follow a 10-K/A cover page when no PART I / Item 1 is present.
        "explanatory note",
        "explanatory statement",
        "report of independent registered public accounting firm",
        "report of independent auditors",
        "index to consolidated financial statements",
    )
    healing_rules: tuple[PhraseSequenceRule, ...] = field(
        default_factory=lambda: tuple(ANNUAL_ADDITIONAL_PHRASE_RULES)
    )


__all__ = [
    "ANNUAL_ADDITIONAL_PHRASE_RULES",
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
    "ANNUAL_BUSINESS_VERBS",
    "ANNUAL_COVER_EXCLUSION_TERMS",
    "ANNUAL_REPORT_TITLES",
    "ANNUAL_TARGET_EXHIBITS",
    "BANKRUPTCY_PROCEEDINGS_TERMS",
    "DELINQUENT_FILERS_TERMS",
    "INCORPORATED_REFERENCE_TERMS",
    "PUBLIC_FLOAT_ANCHOR_RE",
    "PUBLIC_FLOAT_EXACT_RE",
    "PUBLIC_FLOAT_PHRASES",
    "PUBLIC_FLOAT_VALUE_RE",
    "SHARES_ANCHOR_RE",
    "SHARES_PHRASES",
    "SHARES_VALUE_RE",
    "AnnualReportEvidence",
]
