"""Compiled lexical patterns and term tables for conformed signature blocks."""

from __future__ import annotations

import re

from edgar_sec.domain.forms.common.signatures import (
    CORPORATE_OFFICER_TITLES,
    CORPORATE_SIGNATORY_ROLES,
    NOTARY_AND_JURAT_PHRASES,
    POA_AUTH_TERMS,
)
from edgar_sec.domain.taxonomy.legal_forms import LEGAL_FORMS
from edgar_sec.engine.document.signatures import (
    CONFORMED_SIGNATURE_ALT,
    RE_CONFORMED_SIGNER_NAME,
)
from edgar_sec.foundation.regex.builder import build_alternation


CLEAN_LINE_RE = re.compile(r"[_=\-\*]{2,}")

WHITESPACE_RE = re.compile(r"\s+")

PREFIX_STRIP_TERMS = (
    r"by\s*:?",
    r"for\s*:?",
    r"signature\s*:?",
)

PREFIX_STRIP_ALT = build_alternation(PREFIX_STRIP_TERMS, auto_escape=False)

PREFIX_STRIP_RE = re.compile(rf"(?i)^(?:{PREFIX_STRIP_ALT})\s*")

NOTARY_JURAT_ALT = build_alternation(
    NOTARY_AND_JURAT_PHRASES, auto_escape=True, compact=True
)

NOTARY_JURAT_RE = re.compile(NOTARY_JURAT_ALT, re.IGNORECASE)

OFFICER_TITLE_ALT = build_alternation(
    CORPORATE_OFFICER_TITLES, auto_escape=True, compact=True
)

OFFICER_TITLE_RE = re.compile(OFFICER_TITLE_ALT, re.IGNORECASE)

SIGNATORY_ROLE_ALT = build_alternation(
    CORPORATE_SIGNATORY_ROLES, auto_escape=True, compact=True
)

SIGNATORY_ROLE_RE = re.compile(SIGNATORY_ROLE_ALT, re.IGNORECASE)

POA_AUTH_ALT = build_alternation(POA_AUTH_TERMS, auto_escape=True, compact=True)

POA_AUTH_RE = re.compile(POA_AUTH_ALT, re.IGNORECASE)

SIG_NAME_TERMINATOR_ALT = build_alternation(
    [r"\s+\d{1,2}[-/]\d{1,2}[-/]\d{2,4}", r"\n", r"$"],
    auto_escape=False,
)

SIG_NAME_RE = re.compile(
    rf"Signature of Reporting Person(?:\s+Date)?\s+([A-Za-z’‘'\.\- ]+?)(?:{SIG_NAME_TERMINATOR_ALT})",
    re.IGNORECASE,
)

SIG_BY_NAME_TITLE_ALT = build_alternation(
    (
        "accounting",
        "assistant",
        "attorney",
        "chief",
        "comp",
        "counsel",
        "dir",
        "director",
        "exec",
        "executive",
        "financial",
        "general counsel",
        "manager",
        "managing",
        "member",
        "officer",
        "partner",
        "pres",
        "president",
        "principal",
        "prog",
        "sec",
        "secretary",
        "treas",
        "treasurer",
        "trustee",
        "vice",
    ),
    auto_escape=True,
)

SIG_BY_NAME_TERMINATOR_ALT = build_alternation(
    [
        r"\n",
        r"Name\s*:",
        r"Title\s*:",
        r"For\s*:",
        r"Date\b",
        r"\(?\s*POA\b",
        r",?\s+attorney-in-fact\b",
        r"\s*-\s*attorney-in-fact\b",
        r",?\s+attorney\s+in\s+fact\b",
        r",?\s+power\s+of\s+attorney\b",
        r",?\s+authorized\s+signer\b",
        r",?\s+attorney\b",
        r",?\s+poa\b",
        r",?\s+esq\b",
        rf",?\s+(?:{SIG_BY_NAME_TITLE_ALT})\b\.?",
        r"$",
    ],
    auto_escape=False,
)

SIG_BY_NAME_RE = re.compile(
    rf"\bBy\s*:\s*(?:By\s+)?(?:{CONFORMED_SIGNATURE_ALT})?\s*[\"'“”‘’]?"
    r"([A-Za-z][A-Za-z.,’‘\-']*(?:\s+[A-Za-z][A-Za-z.,’‘\-']*){0,5}?)"
    rf"[\"'“”‘’]?(?=\s*(?:{SIG_BY_NAME_TERMINATOR_ALT}))",
    re.IGNORECASE,
)

SIG_DELEGATED_NAME_SUFFIX_ALT = build_alternation(
    ("power of attorney", "attorney-in-fact", "attorney in fact"),
    auto_escape=True,
)

SIG_DELEGATED_SPLIT_RE = re.compile(rf"(?i)\b(?:{SIG_DELEGATED_NAME_SUFFIX_ALT})\b")

SIG_BY_PREFIX_RE = re.compile(r"(?i)^(?:by\s*:?\s*)+")

SIG_TRAILING_PAREN_NUM_RE = re.compile(r"\s*\(\d+\)$")

SIG_CONFORMED_PREFIX_RE = re.compile(rf"(?i)^(?:{CONFORMED_SIGNATURE_ALT})\s*")

SIG_LEADING_RULE_RE = re.compile(r"^[\*_= \-\t_]+")

SIG_RULE_RUN_RE = re.compile(r"[_=]+")

REVERSED_CONFORMED_CELL_RE = re.compile(r"^\s*(?:\*\s*)?s/\s*[A-Za-z]")

SIG_DELEGATED_NAME_RE = re.compile(
    r"(?:^|\n)\s*([A-Za-z][A-Za-z.,’‘\-']*(?:\s+[A-Za-z][A-Za-z.,’‘\-']*){1,5}?)"
    rf"\s*,?\s+(?:{SIG_DELEGATED_NAME_SUFFIX_ALT})\b",
    re.IGNORECASE,
)

SIG_UNDERLINED_NAME_RE = re.compile(
    r"[_=-]{2,}\s*"
    r"([A-Za-z][A-Za-z.,’‘\-']*(?:\s+[A-Za-z][A-Za-z.,’‘\-']*){1,5}?)"
    r"\s*[_=-]{2,}",
    re.IGNORECASE,
)

SIG_PERSON_PREFIX_RE = re.compile(
    r"(?:^|\n)[^\S\r\n]*([A-Za-z’‘'\.\- ]{3,40}?)[^\S\r\n]*\n(?:\s*\d{2,4}\s*\n)?\s*\*{1,2}\s*Signature of Reporting Person",
    re.IGNORECASE,
)

SIG_BOILERPLATE_TERMS: tuple[str, ...] = (
    "criminal",
    "violation",
    "omb number",
    "omb approval",
    "federal",
    "intentional",
    "misstatement",
    "instruction",
    "valid omb",
    "respond",
    "warning",
    "pursuant",
    "reminder",
    "note:",
    "potential persons",
    "displays a currently",
    "18 u.s.c.",
    "15 u.s.c.",
    "sec 1474",
    "sec 2474",
    "table i",
    "table ii",
    "table 1",
    "table 2",
    "cusip",
    "introductory note",
    "schedule 13",
)

SIGNATURE_NAME_PATTERNS: tuple[re.Pattern[str], ...] = (
    RE_CONFORMED_SIGNER_NAME,
    SIG_UNDERLINED_NAME_RE,
    SIG_BY_NAME_RE,
    SIG_DELEGATED_NAME_RE,
    SIG_PERSON_PREFIX_RE,
    SIG_NAME_RE,
)

DISALLOWED_SIGNATURE_NAME_WORDS: frozenset[str] = frozenset(
    (
        "reporting",
        "person",
        "signature",
        "date",
        "power",
        "attorney",
        "fact",
        "units",
        "stock",
        "common",
        "shares",
        "title",
        "security",
        "derivative",
        "month",
        "year",
        "see",
        "instruction",
        "copies",
        "form",
        "page",
        "intentional",
        "misstatements",
        "omissions",
        "facts",
        "constitute",
        "federal",
        "criminal",
        "violations",
        "note",
        "gross",
        "proceeds",
        "market",
        "value",
        "aggregate",
        "approximate",
        "approx",
    )
).union(LEGAL_FORMS)

SIG_DELIMITER_TERMS = (
    r",\s*",
    r"\s+by\b",
    r"\s+as\b",
    r"\s+for\b",
    r"\s+poa\b",
    r"\s+attorney-in-fact\b",
    r"\s+attorney\s+in\s+fact\b",
    r"\s+atty\s+in\s+fact\b",
    r"\s+atty\b",
    r"\s*[\u2013\u2014]\s*",
    r"\s*/\s*",
    r"\n",
    r"\t",
    r"\s{2,}",
)

SIG_DELIMITER_ALT = build_alternation(SIG_DELIMITER_TERMS, auto_escape=False)

SIG_DELIMITER_SPLIT_RE = re.compile(rf"(?i)(?:{SIG_DELIMITER_ALT})")

SIG_LABEL_TERMS = (
    r"\*{0,2}\s*signature\s+of\s+reporting\s+person",
    r"\(?\s*signature\s*\)?",
    r"\(?\s*signed\s*\)?",
)

SIG_LABEL_ALT = build_alternation(SIG_LABEL_TERMS, auto_escape=False)

SIG_LABEL_RE = re.compile(rf"(?i){SIG_LABEL_ALT}")

TITLE_CASE_WORD_RE = re.compile(r"^[A-ZÀ-ÖØ-Þ][a-zA-ZÀ-ÖØ-öø-ÿ’‘'\.\-]*$")

ALL_CAPS_WORD_RE = re.compile(r"^[A-ZÀ-ÖØ-Þ][A-ZÀ-ÖØ-Þ\.\-]*$")

SIG_TRAILING_PAREN_RE = re.compile(r"\s*\([^\)]+\)$")

SIG_SEGMENT_SPLIT_RE = re.compile(r"\s+(?:&|and)\s+")

SIG_NAME_TRIM_CHARS = " ,.-*()_\u2013\u2014/\"'\u201c\u201d\u2018\u2019"

SIG_NAME_TRIM_CHARS_NO_DOT = " ,-*()_\u2013\u2014/\"'\u201c\u201d\u2018\u2019"


__all__ = [
    "CLEAN_LINE_RE",
    "WHITESPACE_RE",
    "PREFIX_STRIP_TERMS",
    "PREFIX_STRIP_ALT",
    "PREFIX_STRIP_RE",
    "NOTARY_JURAT_ALT",
    "NOTARY_JURAT_RE",
    "OFFICER_TITLE_ALT",
    "OFFICER_TITLE_RE",
    "SIGNATORY_ROLE_ALT",
    "SIGNATORY_ROLE_RE",
    "POA_AUTH_ALT",
    "POA_AUTH_RE",
    "SIG_NAME_TERMINATOR_ALT",
    "SIG_NAME_RE",
    "SIG_BY_NAME_TITLE_ALT",
    "SIG_BY_NAME_TERMINATOR_ALT",
    "SIG_BY_NAME_RE",
    "SIG_DELEGATED_NAME_SUFFIX_ALT",
    "SIG_DELEGATED_SPLIT_RE",
    "SIG_BY_PREFIX_RE",
    "SIG_TRAILING_PAREN_NUM_RE",
    "SIG_CONFORMED_PREFIX_RE",
    "SIG_LEADING_RULE_RE",
    "SIG_RULE_RUN_RE",
    "REVERSED_CONFORMED_CELL_RE",
    "SIG_DELEGATED_NAME_RE",
    "SIG_UNDERLINED_NAME_RE",
    "SIG_PERSON_PREFIX_RE",
    "SIG_BOILERPLATE_TERMS",
    "SIGNATURE_NAME_PATTERNS",
    "DISALLOWED_SIGNATURE_NAME_WORDS",
    "SIG_DELIMITER_TERMS",
    "SIG_DELIMITER_ALT",
    "SIG_DELIMITER_SPLIT_RE",
    "SIG_LABEL_TERMS",
    "SIG_LABEL_ALT",
    "SIG_LABEL_RE",
    "TITLE_CASE_WORD_RE",
    "ALL_CAPS_WORD_RE",
    "SIG_TRAILING_PAREN_RE",
    "SIG_SEGMENT_SPLIT_RE",
    "SIG_NAME_TRIM_CHARS",
    "SIG_NAME_TRIM_CHARS_NO_DOT",
]
