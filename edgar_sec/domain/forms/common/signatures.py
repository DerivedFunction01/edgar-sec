"""Shared domain models and lexical evidence for signature blocks."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from edgar_sec.foundation.text.evidence import (
    EvidenceTier,
    LexicalEvidencePack,
)


class DelegationKind(StrEnum):
    """Classification of signature authorization delegation."""

    DIRECT = "direct"
    POWER_OF_ATTORNEY = "power_of_attorney"
    CORPORATE_OFFICER = "corporate_officer"
    AGENT = "agent"


@dataclass(frozen=True, slots=True)
class Signatory:
    """Individual or entity representing a conformed signature."""

    name: str
    title: str | None = None
    date: str | None = None
    delegation_kind: DelegationKind = DelegationKind.DIRECT
    agent_name: str | None = None


@dataclass(frozen=True, slots=True)
class SignatureBlock:
    """Document signature section containing conformed signatories."""

    signatories: tuple[Signatory, ...]
    is_conformed: bool = True
    has_notary: bool = False
    raw_text: str | None = None


CONFORMED_SIGNATURE_TOKENS: tuple[str, ...] = (
    "/s/",
    r"\s\\",
    "/s",
    "s/",
    "[signature]",
    "(signed)",
)

CORPORATE_OFFICER_TITLES: tuple[str, ...] = (
    "vice president",
    "president",
    "corporate secretary",
    "secretary",
    "treasurer",
    "chief executive",
    "chief financial",
    "assistant secretary",
)

CORPORATE_SIGNATORY_ROLES: tuple[str, ...] = (
    "president",
    "manager",
    "general partner",
    "managing member",
    "director",
    "secretary",
    "treasurer",
    "authorized signatory",
    "attorney-in-fact",
    "trustee",
)

NOTARY_AND_JURAT_PHRASES: tuple[str, ...] = (
    "notary public",
    "subscribed and sworn",
    "commission expires",
    "my commission",
    "state of",
    "county of",
)

POA_AUTH_TERMS: tuple[str, ...] = (
    "know all by these presents",
    "power of attorney",
    "for executing forms",
    "attorney-in-fact",
)

SIGNATURE_DECISIVE_PHRASES: tuple[str, ...] = (
    "signature of reporting person",
    "signature of",
    "intentional misstatements",
    "federal criminal violations",
    "power of attorney",
    "attorney in fact",
    "know all by these presents",
    "for executing forms",
    "notary public",
    "subscribed and sworn",
    "commission expires",
    "my commission",
    "state of",
    "county of",
    "very truly yours",
    "authorized signatory",
    "managing member",
    "general partner",
)

SIGNATURE_STRONG_NGRAMS: tuple[str, ...] = (
    "print name",
    "vice president",
    "corporate secretary",
    "chief executive",
    "chief financial",
    "assistant secretary",
)

SIGNATURE_STRONG_UNIGRAMS: tuple[str, ...] = (
    "signature",
    "title",
    "president",
    "secretary",
    "treasurer",
    "trustee",
    "manager",
    "director",
    "officer",
    "by",
)

SIGNATURE_SUPPORT_TERMS: tuple[str, ...] = (
    "date",
    "dated",
    "address",
    "capacity",
    "duly",
    "authorized",
    "executed",
    "behalf",
    "by",
)

COMMON_SIGNATURE_LEXICAL_PACK = LexicalEvidencePack(
    name="common_signature",
    tiers=(
        EvidenceTier(
            name="signature_decisive",
            priority=30,
            value=3,
            terms=SIGNATURE_DECISIVE_PHRASES,
            match_kind="ngram",
            min_distinct_hits=1,
        ),
        EvidenceTier(
            name="signature_strong_ngram",
            priority=25,
            value=2,
            terms=SIGNATURE_STRONG_NGRAMS,
            match_kind="ngram",
            min_distinct_hits=1,
        ),
        EvidenceTier(
            name="signature_strong_unigram",
            priority=20,
            value=2,
            terms=SIGNATURE_STRONG_UNIGRAMS,
            match_kind="unigram",
            min_distinct_hits=2,
        ),
        EvidenceTier(
            name="signature_support",
            priority=10,
            value=1,
            terms=SIGNATURE_SUPPORT_TERMS,
            match_kind="unigram",
            min_distinct_hits=2,
            support=True,
        ),
    ),
    exclusion_terms=("non-derivative", "derivative"),
)
