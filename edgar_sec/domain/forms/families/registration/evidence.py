"""Registration statement evidence definitions and semantic anchors."""

from __future__ import annotations

from dataclasses import dataclass, field

from edgar_sec.domain.forms.common.forward_looking import (
    FORWARD_LOOKING_TERMS,
    FORWARD_LOOKING_VERBS,
)
from edgar_sec.domain.forms.families.annual.evidence import (
    ANNUAL_COVER_EXCLUSION_TERMS,
)
from edgar_sec.foundation.text.automaton import CaseMode
from edgar_sec.foundation.text.evidence import EvidenceTier, LexicalEvidencePack
from edgar_sec.foundation.text.healing import PhraseSequenceRule

REGISTRATION_REPORT_TITLES: tuple[str, ...] = (
    "form s-1",
    "registration statement under the securities act of 1933",
    "pre-effective amendment no.",
    "post-effective amendment no.",
    "amendment no.",
)

S3_REPORT_TITLES: tuple[str, ...] = (
    "form s-3",
    "form s-3asr",
    "form s-3d",
    "registration statement under the securities act of 1933",
    "pre-effective amendment no.",
    "post-effective amendment no.",
    "amendment no.",
)

S4_REPORT_TITLES: tuple[str, ...] = (
    "form s-4",
    "form s-4ef",
    "registration statement under the securities act of 1933",
    "pre-effective amendment no.",
    "post-effective amendment no.",
    "amendment no.",
)

S8_REPORT_TITLES: tuple[str, ...] = (
    "form s-8",
    "form s-8pos",
    "registration statement under the securities act of 1933",
    "pre-effective amendment no.",
    "post-effective amendment no.",
    "amendment no.",
)

REGISTRATION_SHAPE_TERMS: tuple[str, ...] = (
    "approximate date of commencement of proposed sale to the public",
    "approximate date of commencement of proposed sale",
    "agent for service",
    "primary standard industrial classification code number",
    "primary standard industrial classification",
    "calculation of registration fee",
    "calculation of filing fee tables",
    "calculation of filing fee",
    "proposed maximum offering price",
    "proposed maximum aggregate offering price",
)

# Decisive registration body phrases: 2-3 word hits confirming early body prose.
# Focused strictly on immediate post-cover / early prospectus transitions.
REGISTRATION_BODY_PHRASES: tuple[str, ...] = (
    # Core pronoun-verb anchors
    "we have",
    "we are",
    "we will",
    "we conduct",
    "our company",
    "our business",
    "our common stock",
    "our operations",
    "our products",
    "our services",
    "our strategy",
    "our stockholders",
    "our shareholders",
    "you should rely",
    # Prospectus early structural anchors
    "prospectus summary",
    "summary highlights",
    "this summary",
    "use of proceeds",
    "selling stockholders",
    "selling shareholders",
    "selling securityholders",
    "plan of distribution",
    "description of capital",
    "description of securities",
    # Transaction & merger anchors (Form S-4)
    "the merger",
    "merger agreement",
    "the exchange offer",
    "special meeting",
    "questions and answers",
    # Benefit plan anchors (Form S-8)
    "incorporation of documents by reference",
)

REGISTRATION_BODY_SOFT_PHRASES: tuple[str, ...] = (
    "safe harbor",
    "cautionary statements",
    "cautionary note",
    "undue reliance",
    "statements include",
    "future performance",
    "unless the context",
    "about this prospectus",
)

REGISTRATION_BODY_HEADER_PHRASES: tuple[str, ...] = (
    "our company",
    "our business",
    "the offering",
)

REGISTRATION_BODY_HEADER_TERMS: tuple[str, ...] = (
    "business",
    "description",
    "operations",
    "general",
    "overview",
    "prospectus",
    "summary",
    "offering",
    "underwriting",
)

REGISTRATION_BODY_STRONG_TERMS: tuple[str, ...] = (
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
    "underwriters",
    "dilution",
    "capitalization",
    "proceeds",
    "subordinated",
    "debentures",
    "indemnification",
)

REGISTRATION_BUSINESS_VERBS: tuple[str, ...] = (
    "provides",
    "operates",
    "manufactures",
    "sells",
    "develops",
    "distributes",
    "manages",
)

REGISTRATION_BODY_VERBS: tuple[str, ...] = (
    *REGISTRATION_BUSINESS_VERBS,
    *FORWARD_LOOKING_VERBS[:5],
)

REGISTRATION_BODY_FORWARD_TERMS: tuple[str, ...] = tuple(
    term for term in FORWARD_LOOKING_TERMS if term not in ("certain", "may")
)

REGISTRATION_BODY_GENERAL_TERMS: tuple[str, ...] = (
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

REGISTRATION_BODY_WEAK_TERMS: tuple[str, ...] = (
    *REGISTRATION_BODY_VERBS,
    "offered",
    "registered",
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

REGISTRATION_COVER_EXCLUSION_TERMS: tuple[str, ...] = (
    *ANNUAL_COVER_EXCLUSION_TERMS,
    "securities",
    "act",
    "address",
    "telephone",
    "agent",
    "service",
    "state",
    "incorporation",
    "employer",
    "identification",
    "fee",
    "calculation",
    "antidilution",
)

REGISTRATION_BODY_LEXICAL_PACK = LexicalEvidencePack(
    name="registration_body_start",
    tiers=(
        EvidenceTier(
            name="body_phrase",
            priority=30,
            value=3,
            terms=REGISTRATION_BODY_PHRASES,
            match_kind="ngram",
            min_distinct_hits=1,
        ),
        EvidenceTier(
            name="body_strong",
            priority=20,
            value=2,
            terms=REGISTRATION_BODY_STRONG_TERMS,
            match_kind="unigram",
            min_distinct_hits=2,
        ),
        EvidenceTier(
            name="body_forward",
            priority=20,
            value=2,
            terms=REGISTRATION_BODY_FORWARD_TERMS,
            match_kind="unigram",
            case_mode=CaseMode.LOWERCASE,
            min_distinct_hits=2,
        ),
        EvidenceTier(
            name="body_header",
            priority=20,
            value=2,
            terms=REGISTRATION_BODY_HEADER_TERMS,
            match_kind="unigram",
            min_distinct_hits=2,
        ),
        EvidenceTier(
            name="body_header_phrase",
            priority=20,
            value=2,
            terms=REGISTRATION_BODY_HEADER_PHRASES,
            match_kind="ngram",
            min_distinct_hits=1,
        ),
        EvidenceTier(
            name="body_phrase_soft",
            priority=15,
            value=1,
            terms=REGISTRATION_BODY_SOFT_PHRASES,
            match_kind="ngram",
            min_distinct_hits=1,
            support=True,
        ),
        EvidenceTier(
            name="body_general",
            priority=10,
            value=1,
            terms=REGISTRATION_BODY_GENERAL_TERMS,
            match_kind="unigram",
            min_distinct_hits=2,
        ),
        EvidenceTier(
            name="body_weak",
            priority=10,
            value=1,
            terms=REGISTRATION_BODY_WEAK_TERMS,
            match_kind="unigram",
            min_distinct_hits=2,
        ),
    ),
    exclusion_terms=REGISTRATION_COVER_EXCLUSION_TERMS,
)


@dataclass(frozen=True, slots=True)
class RegistrationEvidence:
    """Consolidated registration statement evidence pack."""

    shape_terms: tuple[str, ...] = REGISTRATION_SHAPE_TERMS
    body_ngrams: tuple[str, ...] = (
        *REGISTRATION_BODY_PHRASES,
        *REGISTRATION_BODY_HEADER_PHRASES,
    )
    body_verbs: tuple[str, ...] = REGISTRATION_BODY_VERBS
    body_terms: tuple[str, ...] = (
        *REGISTRATION_BODY_STRONG_TERMS,
        *REGISTRATION_BODY_HEADER_TERMS,
    )
    cover_terms: tuple[str, ...] = REGISTRATION_COVER_EXCLUSION_TERMS
    healing_rules: list[PhraseSequenceRule] = field(default_factory=list)
    body_lexical: LexicalEvidencePack = REGISTRATION_BODY_LEXICAL_PACK
    forward_terms: tuple[str, ...] = REGISTRATION_BODY_FORWARD_TERMS
    header_terms: tuple[str, ...] = REGISTRATION_BODY_HEADER_TERMS
    header_phrases: tuple[str, ...] = REGISTRATION_BODY_HEADER_PHRASES
    soft_phrases: tuple[str, ...] = REGISTRATION_BODY_SOFT_PHRASES
    general_terms: tuple[str, ...] = REGISTRATION_BODY_GENERAL_TERMS


__all__ = [
    "REGISTRATION_BODY_FORWARD_TERMS",
    "REGISTRATION_BODY_GENERAL_TERMS",
    "REGISTRATION_BODY_HEADER_PHRASES",
    "REGISTRATION_BODY_HEADER_TERMS",
    "REGISTRATION_BODY_LEXICAL_PACK",
    "REGISTRATION_BODY_PHRASES",
    "REGISTRATION_BODY_SOFT_PHRASES",
    "REGISTRATION_BODY_STRONG_TERMS",
    "REGISTRATION_BODY_VERBS",
    "REGISTRATION_BODY_WEAK_TERMS",
    "REGISTRATION_COVER_EXCLUSION_TERMS",
    "REGISTRATION_REPORT_TITLES",
    "REGISTRATION_SHAPE_TERMS",
    "RegistrationEvidence",
    "S3_REPORT_TITLES",
    "S4_REPORT_TITLES",
    "S8_REPORT_TITLES",
]
