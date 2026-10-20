"""Shared statutory warning evidence, OMB disclosures, and legal notices."""

from __future__ import annotations

from edgar_sec.foundation.text.evidence import (
    EvidenceTier,
    LexicalEvidencePack,
)
from edgar_sec.domain.forms.common.phrases import (
    PhraseCategory,
    PhraseRule,
)

STATUTORY_CRIMINAL_WARNING_PHRASES: tuple[str, ...] = (
    "intentional misstatements or omissions of facts constitute federal criminal violations",
    "intentional misstatements or omission of facts constitute federal criminal violations",
    "see 18 u.s.c. 1001",
    "see 18 usc 1001",
    "18 u.s.c. 1001",
    "15 u.s.c. 78ff",
    "15 usc 78ff",
    "federal criminal violations",
)

HEADER_LEAK_PHRASES: tuple[str, ...] = (
    "deemed execution",
    "date of original",
    "title of security",
    "individual or joint",
    "price of derivative",
    "amount or number",
    "conversion or exercise",
)

STATUTORY_PAGE_BOILERPLATE: tuple[str, ...] = (
    "reminder: report on a separate",
    "potential persons who are to respond",
    "note: file three copies",
    "see instruction 4(b)(v)",
    "see instruction 6 for procedure",
    "sec 1474",
    "sec 2474",
    "(over)",
    "persons who respond to the collection",
)

STATUTORY_DECISIVE_PHRASES: tuple[str, ...] = (
    "reminder report on a separate",
    "potential persons who are to respond",
    "note file three copies",
    "see instruction",
    "sec 1474",
    "sec 2474",
    "collection of information",
    "omb approval",
    "currently valid omb",
)

STATUTORY_STRONG_NGRAMS: tuple[str, ...] = ("company address",)

STATUTORY_STRONG_UNIGRAMS: tuple[str, ...] = (
    "agent",
    "fax",
    "phone",
    "toll",
    "logo",
    "tel",
)

STATUTORY_SUPPORT_TERMS: tuple[str, ...] = (
    "copies",
    "procedure",
    "separate",
    "respond",
    "control",
    "number",
)

COMMON_STATUTORY_LEXICAL_PACK = LexicalEvidencePack(
    name="common_statutory",
    tiers=(
        EvidenceTier(
            name="statutory_decisive",
            priority=30,
            value=3,
            terms=STATUTORY_DECISIVE_PHRASES,
            match_kind="ngram",
            min_distinct_hits=1,
        ),
        EvidenceTier(
            name="statutory_strong_ngram",
            priority=25,
            value=2,
            terms=STATUTORY_STRONG_NGRAMS,
            match_kind="ngram",
            min_distinct_hits=1,
        ),
        EvidenceTier(
            name="statutory_strong_unigram",
            priority=20,
            value=2,
            terms=STATUTORY_STRONG_UNIGRAMS,
            match_kind="unigram",
            min_distinct_hits=2,
        ),
        EvidenceTier(
            name="statutory_support",
            priority=10,
            value=1,
            terms=STATUTORY_SUPPORT_TERMS,
            match_kind="unigram",
            min_distinct_hits=2,
            support=True,
        ),
    ),
)

RULE_10B5_1_PHRASES: tuple[str, ...] = (
    "affirmative defense conditions of rule 10b5-1(c)",
    "affirmative defense conditions of rule 10b5-1",
    "date of plan adoption or giving of instruction",
    "satisfy rule 10b5-1",
    "written trading plan",
    "trading instructions to satisfy rule 10b5-1",
    "relying on rule 10b5-1",
    "rule 10b5-1(c)",
    "rule 10b5-1",
)

CERTIFICATION_DECLARATION_PHRASES: tuple[str, ...] = (
    "after reasonable inquiry and to the best of my knowledge and belief",
    "i certify that the information set forth in this statement is true",
    "true, complete and correct",
    "true complete and correct",
    "terms of submission",
    "undertaking to furnish",
)

OMB_BURDEN_PHRASES: tuple[str, ...] = (
    "estimated average burden hours per response",
    "average burden hours per response",
    "burden hours per response",
    "omb number",
    "currently valid omb control number",
)

COMMON_FORM_PHRASE_RULES = (
    PhraseRule(
        "statutory.header_leak",
        tuple((phrase,) for phrase in HEADER_LEAK_PHRASES),
        PhraseCategory.TABLE_HEADING,
    ),
    PhraseRule(
        "statutory.criminal_warning",
        tuple((phrase,) for phrase in STATUTORY_CRIMINAL_WARNING_PHRASES),
        PhraseCategory.WARNING,
    ),
    PhraseRule(
        "statutory.page_boilerplate",
        tuple((phrase,) for phrase in STATUTORY_PAGE_BOILERPLATE),
        PhraseCategory.BOILERPLATE,
    ),
    PhraseRule(
        "statutory.certification",
        tuple((phrase,) for phrase in CERTIFICATION_DECLARATION_PHRASES),
        PhraseCategory.CERTIFICATION,
    ),
    PhraseRule(
        "statutory.omb_burden",
        tuple((phrase,) for phrase in OMB_BURDEN_PHRASES),
        PhraseCategory.OMB_NOTICE,
    ),
    PhraseRule(
        "statutory.rule_10b5_1",
        tuple((phrase,) for phrase in RULE_10B5_1_PHRASES),
        PhraseCategory.INSTRUCTION,
    ),
)

__all__ = [
    "CERTIFICATION_DECLARATION_PHRASES",
    "COMMON_STATUTORY_LEXICAL_PACK",
    "COMMON_FORM_PHRASE_RULES",
    "HEADER_LEAK_PHRASES",
    "OMB_BURDEN_PHRASES",
    "RULE_10B5_1_PHRASES",
    "STATUTORY_CRIMINAL_WARNING_PHRASES",
    "STATUTORY_DECISIVE_PHRASES",
    "STATUTORY_PAGE_BOILERPLATE",
    "STATUTORY_STRONG_NGRAMS",
    "STATUTORY_STRONG_UNIGRAMS",
    "STATUTORY_SUPPORT_TERMS",
]
