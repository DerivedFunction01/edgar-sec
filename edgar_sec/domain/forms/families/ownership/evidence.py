"""Ownership report family evidence definitions, lexical packs, and vetoes."""

from __future__ import annotations

from edgar_sec.domain.forms.common.phrases import (
    PhraseCategory,
    PhraseEffect,
    PhraseRule,
)
from edgar_sec.foundation.text.evidence import EvidenceTier, LexicalEvidencePack

FOOTNOTE_DECISIVE_PHRASES: tuple[str, ...] = (
    "explanation of responses",
    "footnote description",
    "footnote descriptions",
    "restricted stock units",
    "restricted stock",
    "vesting schedule",
    "shares withheld to satisfy",
    "subject to forfeiture",
    "deferred compensation",
    "automatic reinvestment",
    "power of attorney",
    "weighted average",
)

FOOTNOTE_STRONG_VERBS: tuple[str, ...] = (
    "vesting",
    "vest",
    "vests",
    "forfeiture",
    "withheld",
    "settled",
    "installments",
    "exercisable",
    "pursuant",
    "reinvestment",
    "satisfy",
)

FOOTNOTE_SUPPORT_TERMS: tuple[str, ...] = (
    "grant",
    "units",
    "plan",
    "compensation",
    "deferred",
    "incentive",
    "dividend",
    "stock",
    "common",
)

FOOTNOTE_EXCLUSION_TERMS: tuple[str, ...] = (
    "ticker",
    "irs",
)

FOOTNOTE_VETO_PHRASES: tuple[str, ...] = (
    "name and address of reporting person",
    "issuer name and ticker",
    "table i",
    "table ii",
    "non-derivative",
    "title of security",
    "title of derivative",
    "signature of reporting person",
)

OWNERSHIP_FOOTNOTE_LEXICAL_PACK = LexicalEvidencePack(
    name="ownership_footnote",
    tiers=(
        EvidenceTier(
            name="footnote_decisive",
            priority=30,
            value=3,
            terms=FOOTNOTE_DECISIVE_PHRASES,
            match_kind="ngram",
            min_distinct_hits=1,
        ),
        EvidenceTier(
            name="footnote_strong",
            priority=20,
            value=2,
            terms=FOOTNOTE_STRONG_VERBS,
            match_kind="unigram",
            min_distinct_hits=2,
        ),
        EvidenceTier(
            name="footnote_support",
            priority=10,
            value=1,
            terms=FOOTNOTE_SUPPORT_TERMS,
            match_kind="unigram",
            min_distinct_hits=2,
            support=True,
        ),
    ),
    exclusion_terms=FOOTNOTE_EXCLUSION_TERMS,
)

OWNERSHIP_FORM_NAMES: tuple[str, ...] = ("form 3", "form 4", "form 5")

PROSE_BOILERPLATE_TERMS: tuple[str, ...] = (
    "check this box if no longer",
    "check this box if no longer subject",
    "form 4 or form 5 obligations",
    "see instruction",
    "washington, d.c.",
    "securities and exchange commission",
    "statement of changes in beneficial ownership",
    "name and address of reporting person",
    "name and address",
    "(print or type responses)",
    "print or type responses",
    "issuer name and ticker",
    "ticker or trading symbol",
    "or trading symbol",
    "trading symbol",
    "i.r.s. identification number",
    "if an entity (voluntary)",
    "statement for month/day/year",
    "if amendment, date of original",
    "relationship of reporting person",
    "to issuer",
    "check all applicable",
    "individual or joint/group filing",
    "table i - non-derivative",
    "table ii - derivative",
    "reminder: report on a separate line",
    "report on a separate line for each class",
    "potential persons who are to respond",
    "*intentional misstatements",
    "**signature of reporting person",
    "person* (last, first, middle)",
    "last, first, middle",
    "(last, first, middle)",
    "if an entity",
    *OWNERSHIP_FORM_NAMES,
)

OWNERSHIP_PROSE_BOILERPLATE_RULE = PhraseRule(
    "ownership.prose_boilerplate",
    tuple((phrase,) for phrase in PROSE_BOILERPLATE_TERMS),
    PhraseCategory.BOILERPLATE,
    effect=PhraseEffect.EXCLUDE_FROM_VALUE,
    family_ids=frozenset({"ownership"}),
)


TABLE_I_HOLDING_PHRASES: tuple[str, ...] = (
    "amount of securities beneficially owned",
    "beneficially owned at end of month",
    "ownership form",
)

TABLE_I_DECISIVE_PHRASES: tuple[str, ...] = (
    "non derivative",
    "table i",
    "title of security",
    "amount of securities beneficially owned",
    "securities beneficially owned",
    "beneficially owned at end of month",
)

TABLE_I_STRONG_PHRASES: tuple[str, ...] = (
    "ownership form",
    "amount of securities",
    "securities acquired",
    "securities disposed",
)

TABLE_I_SUPPORT_TERMS: tuple[str, ...] = (
    "security",
    "acquired",
    "disposed",
    "beneficially",
    "owned",
    "direct",
    "indirect",
)

OWNERSHIP_TABLE_I_LEXICAL_PACK = LexicalEvidencePack(
    name="ownership_table_i",
    tiers=(
        EvidenceTier(
            name="table_i_decisive",
            priority=30,
            value=3,
            terms=TABLE_I_DECISIVE_PHRASES,
            match_kind="ngram",
            min_distinct_hits=1,
        ),
        EvidenceTier(
            name="table_i_strong",
            priority=20,
            value=2,
            terms=TABLE_I_STRONG_PHRASES,
            match_kind="ngram",
            min_distinct_hits=1,
        ),
        EvidenceTier(
            name="table_i_support",
            priority=10,
            value=1,
            terms=TABLE_I_SUPPORT_TERMS,
            match_kind="unigram",
            min_distinct_hits=2,
            support=True,
        ),
    ),
)

TABLE_II_DECISIVE_PHRASES: tuple[str, ...] = (
    "table ii",
    "title of derivative",
    "derivative security",
    "derivative securities",
    "exercise price of derivative",
    "conversion or exercise",
    "price of derivative",
    "date exercisable",
    "expiration date",
    "underlying securities",
)

TABLE_II_STRONG_UNIGRAMS: tuple[str, ...] = ("derivative",)

TABLE_II_SUPPORT_TERMS: tuple[str, ...] = (
    "exercisable",
    "conversion",
    "exercise",
    "warrants",
    "options",
)

OWNERSHIP_TABLE_II_LEXICAL_PACK = LexicalEvidencePack(
    name="ownership_table_ii",
    tiers=(
        EvidenceTier(
            name="table_ii_decisive",
            priority=30,
            value=3,
            terms=TABLE_II_DECISIVE_PHRASES,
            match_kind="ngram",
            min_distinct_hits=1,
        ),
        EvidenceTier(
            name="table_ii_strong",
            priority=20,
            value=2,
            terms=TABLE_II_STRONG_UNIGRAMS,
            match_kind="unigram",
            min_distinct_hits=1,
        ),
        EvidenceTier(
            name="table_ii_support",
            priority=10,
            value=1,
            terms=TABLE_II_SUPPORT_TERMS,
            match_kind="unigram",
            min_distinct_hits=2,
            support=True,
        ),
    ),
    exclusion_terms=("non",),
)

BOXES_DECISIVE_PHRASES: tuple[str, ...] = (
    "name and address of reporting person",
    "name and address",
    "reporting person",
    "issuer name",
    "trading symbol",
    "ticker symbol",
    "statement for month",
    "statement for year",
    "date of event requiring statement",
    "date of event",
    "statement for issuer fiscal year ended",
    "fiscal year ended",
    "earliest transaction required",
    "identification number",
    "irs identification",
    "joint group filing",
    "joint filing",
    "group filing",
    "date of original",
    "if amendment",
    "relationship of reporting person",
    "designated filer",
    "one reporting person",
    "more than one reporting person",
    "month day",
    "month year",
    "i d number",
)

BOXES_STRONG_TERMS: tuple[str, ...] = (
    "last",
    "first",
    "middle",
    "street",
    "city",
    "state",
    "zip",
    "director",
    "officer",
    "owner",
    "issuer",
    "symbol",
    "amendment",
)

BOXES_SUPPORT_TERMS: tuple[str, ...] = (
    "relationship",
    "individual",
    "voluntary",
    "applicable",
)

OWNERSHIP_BOXES_LEXICAL_PACK = LexicalEvidencePack(
    name="ownership_boxes",
    tiers=(
        EvidenceTier(
            name="boxes_decisive",
            priority=30,
            value=3,
            terms=BOXES_DECISIVE_PHRASES,
            match_kind="ngram",
            min_distinct_hits=1,
        ),
        EvidenceTier(
            name="boxes_strong",
            priority=20,
            value=2,
            terms=BOXES_STRONG_TERMS,
            match_kind="unigram",
            min_distinct_hits=2,
        ),
        EvidenceTier(
            name="boxes_support",
            priority=10,
            value=1,
            terms=BOXES_SUPPORT_TERMS,
            match_kind="unigram",
            min_distinct_hits=2,
            support=True,
        ),
    ),
    exclusion_terms=("signature",),
)

HEADER_DECISIVE_PHRASES: tuple[str, ...] = (
    "check this box if no longer",
    "check box if no longer",
    "omb approval",
    "statement of changes in beneficial ownership",
    "statement of beneficial ownership",
    "initial statement of beneficial ownership",
    "annual statement of beneficial ownership",
    "changes in beneficial ownership",
    "form 3 holdings reported",
    "form 4 transactions reported",
    "filed pursuant to",
    "continuation statement",
)

HEADER_SUPPORT_TERMS: tuple[str, ...] = (
    "securities",
    "exchange",
    "commission",
    "washington",
    "ticker",
    "pursuant",
    "ownership",
)

OWNERSHIP_HEADER_LEXICAL_PACK = LexicalEvidencePack(
    name="ownership_header",
    tiers=(
        EvidenceTier(
            name="header_decisive",
            priority=30,
            value=3,
            terms=HEADER_DECISIVE_PHRASES,
            match_kind="ngram",
            min_distinct_hits=1,
        ),
        EvidenceTier(
            name="header_support",
            priority=10,
            value=1,
            terms=HEADER_SUPPORT_TERMS,
            match_kind="unigram",
            min_distinct_hits=2,
            support=True,
        ),
    ),
)


__all__ = [
    "BOXES_DECISIVE_PHRASES",
    "BOXES_STRONG_TERMS",
    "BOXES_SUPPORT_TERMS",
    "FOOTNOTE_DECISIVE_PHRASES",
    "FOOTNOTE_EXCLUSION_TERMS",
    "FOOTNOTE_STRONG_VERBS",
    "FOOTNOTE_SUPPORT_TERMS",
    "FOOTNOTE_VETO_PHRASES",
    "HEADER_DECISIVE_PHRASES",
    "HEADER_SUPPORT_TERMS",
    "OWNERSHIP_BOXES_LEXICAL_PACK",
    "OWNERSHIP_FOOTNOTE_LEXICAL_PACK",
    "OWNERSHIP_FORM_NAMES",
    "OWNERSHIP_PROSE_BOILERPLATE_RULE",
    "OWNERSHIP_HEADER_LEXICAL_PACK",
    "OWNERSHIP_TABLE_I_LEXICAL_PACK",
    "OWNERSHIP_TABLE_II_LEXICAL_PACK",
    "PROSE_BOILERPLATE_TERMS",
    "TABLE_I_DECISIVE_PHRASES",
    "TABLE_I_HOLDING_PHRASES",
    "TABLE_I_STRONG_PHRASES",
    "TABLE_I_SUPPORT_TERMS",
    "TABLE_II_DECISIVE_PHRASES",
    "TABLE_II_STRONG_UNIGRAMS",
    "TABLE_II_SUPPORT_TERMS",
]
