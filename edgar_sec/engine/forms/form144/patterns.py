"""Compiled regular expression patterns and vocabulary for Form 144 parsing."""

from __future__ import annotations

import re

from edgar_sec.domain.forms.families.form144.evidence import (
    FORM144_BOX_1_2_DECISIVE_PHRASES,
    FORM144_INSTRUCTION_PHRASE_RULE,
)
from edgar_sec.engine.forms.common.phrases import (
    PhraseMatch,
    compile_phrase_rules,
    match_phrase_rules,
)
from edgar_sec.engine.forms.common.tables import IGNORE_SUBBOX_MARKERS
from edgar_sec.foundation.regex.builder import build_alternation
from edgar_sec.foundation.text.dates import NUMERIC_DATE_RE, RE_FULL_DATE

SEC_FILE_LABEL_RE = re.compile(
    r"(?:s\.?e\.?c\.?\s*file\s*(?:no\.?|number)?|file\s*no\.?)\s*[:\s]*([0-9]{1,3}-[0-9]{4,7})",
    re.IGNORECASE,
)
SEC_FILE_BARE_RE = re.compile(r"\b([0-9]{1,3}-[0-9]{4,7})\b")
PHONE_RE = re.compile(r"\(?\b\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b")
_NOTICE_DATE_PAT = rf"({RE_FULL_DATE.pattern}|{NUMERIC_DATE_RE.pattern})"
NOTICE_DATE_LABEL_RE = re.compile(
    rf"(?:(?:date of notice|date\s*:?)\s*[:\s]*{_NOTICE_DATE_PAT}|{_NOTICE_DATE_PAT}\s*date of notice)",
    re.IGNORECASE,
)

PLAN_ADOPTION_TERMS: tuple[str, ...] = ("plan adoption", "instruction", "rule 10b5-1")
PLAN_ADOPTION_ALT = build_alternation(PLAN_ADOPTION_TERMS)
PLAN_ADOPTION_RE = re.compile(
    rf"(?:{PLAN_ADOPTION_ALT})[^\d]{{1,50}}{_NOTICE_DATE_PAT}",
    re.IGNORECASE,
)


_COMPILED_FORM144_INSTRUCTION_RULE = compile_phrase_rules(
    (FORM144_INSTRUCTION_PHRASE_RULE,)
)
FORM144_NUMBERED_INSTRUCTION_RE = re.compile(
    r"^\s*[123]\s*\.\s*\(\s*[a-g]\s*\)", re.IGNORECASE
)


def form144_instruction_matches(text: str) -> tuple[PhraseMatch, ...]:
    return match_phrase_rules(
        text,
        _COMPILED_FORM144_INSTRUCTION_RULE,
        family_id="144",
    )


def is_form144_instruction_line(line: str) -> bool:
    """Detect whether a line is numbered instruction boilerplate or a veto phrase."""
    if (
        BOX_1A_LABEL_RE.search(line)
        or BOX_2A_LABEL_RE.search(line)
        or BOX_3A_TITLE_RE.search(line)
    ):
        return False
    if FORM144_NUMBERED_INSTRUCTION_RE.search(line):
        return True
    return bool(form144_instruction_matches(line))


SECURITY_CLASS_TERMS: tuple[str, ...] = (
    "common",
    "class a",
    "class b",
    "class c",
    "preferred",
    "ordinary",
    "notes",
    "conv",
    "debentures",
    "warrants",
    "options",
    "debt",
)
SECURITY_CLASS_ALT = build_alternation(SECURITY_CLASS_TERMS)
SECURITY_CLASS_RE = re.compile(rf"\b({SECURITY_CLASS_ALT})\b", re.IGNORECASE)

BOX_1A_LABEL_RE = re.compile(
    r"(?:1\.?\s*\(\s*a\s*\)|NAME\s+OF\s+ISSUER)", re.IGNORECASE
)
BOX_1A_TAIL_RE = re.compile(r"1\.?\s*\(\s*a\s*\)[^:]*:\s*(.+)$", re.IGNORECASE)
BOX_1B_IRS_LABEL_RE = re.compile(
    r"(?:1\.?\s*\(\s*b\s*\)|\(\s*b\s*\))\s*IRS", re.IGNORECASE
)
BOX_1C_SEC_LABEL_RE = re.compile(
    r"(?:1\.?\s*\(\s*c\s*\)|\(\s*c\s*\))\s*S?\.?E?\.?C?", re.IGNORECASE
)

BOX_2A_LABEL_RE = re.compile(
    r"(?:2\.?\s*\(\s*a\s*\)|NAME\s+OF\s+PERSON\s+FOR\s+WHOSE\s+ACCOUNT)",
    re.IGNORECASE,
)
BOX_2A_TAIL_RE = re.compile(r"2\.?\s*\(\s*a\s*\)[^:]*:\s*(.+)$", re.IGNORECASE)
RELATIONSHIP_LABEL_RE = re.compile(r"RELATIONSHIP\s+TO\s+ISSUER", re.IGNORECASE)
RELATIONSHIP_TAIL_RE = re.compile(
    r"RELATIONSHIP\s+TO\s+ISSUER\s*:?\s*(.+)$", re.IGNORECASE
)

BOX_3A_TITLE_RE = re.compile(
    r"(?:3\.?\s*\(\s*a\s*\)|Title\s+of\s+(?:the\s+)?Class)", re.IGNORECASE
)
BOX_3A_TAIL_RE = re.compile(r"3\.?\s*\(\s*a\s*\)[^:]*:\s*(.+)$", re.IGNORECASE)
TABLE_I_MARKER_RE = re.compile(r"\btable\s+(?:ii?|1)\b", re.IGNORECASE)

_UNITS_TERMS = (
    "number of shares",
    "number of share",
    "number of units",
    "number of unit",
    "units to be sold",
    "unit to be sold",
)
_UNITS_ALT = build_alternation(_UNITS_TERMS)
BOX_3C_UNITS_RE = re.compile(
    rf"(?:3\.?\s*\(\s*c\s*\)|\(\s*c\s*\))\s*(?:{_UNITS_ALT})", re.IGNORECASE
)
BOX_3C_TAIL_RE = re.compile(
    r"(?:to be sold|\(c\)[^:]*):?\s*([0-9][0-9,]*(?:\.[0-9]+)?\s*[A-Za-z]*)",
    re.IGNORECASE,
)
BOX_3C_NEXT_LINE_RE = re.compile(
    r"(?:instr\.\s*3\(c\):\s*)?([0-9][0-9,]*(?:\.[0-9]+)?\s*[A-Za-z]*)",
    re.IGNORECASE,
)

BOX_3D_MARKET_VALUE_RE = re.compile(
    r"(?:3\.?\s*\(\s*d\s*\)|\(\s*d\s*\))\s*Aggregate\s+Market", re.IGNORECASE
)
BOX_3D_TAIL_RE = re.compile(
    r"market\s+value[^:]*:?\s*([\$€£]?\s*[0-9][0-9,]*(?:\.[0-9]+)?\s*[A-Za-z]*)",
    re.IGNORECASE,
)
BOX_3G_EXCHANGE_RE = re.compile(
    r"(?:3\.?\s*\(\s*g\s*\)|\(\s*g\s*\))\s*Name\s+of\s+Each\s+Securities\s+Exchange",
    re.IGNORECASE,
)

COVER_HEADER_OR_SUBBOX_TERMS: frozenset[str] = frozenset(
    FORM144_BOX_1_2_DECISIVE_PHRASES
    + (
        "file no",
        "work location",
        "telephone no",
        "please type",
        "code",
        "address",
        "name of person",
        "whose account",
        "securities are to be sold",
        "to be sold",
    )
)


def is_cover_header_or_subbox_line(text: str) -> bool:
    """Check if text is a subbox label marker or cover header term."""
    low = text.lower().strip()
    if low.startswith(IGNORE_SUBBOX_MARKERS):
        return True
    return any(term in low for term in COVER_HEADER_OR_SUBBOX_TERMS)


__all__ = [
    "BOX_1A_LABEL_RE",
    "BOX_1A_TAIL_RE",
    "BOX_1B_IRS_LABEL_RE",
    "BOX_1C_SEC_LABEL_RE",
    "BOX_2A_LABEL_RE",
    "BOX_2A_TAIL_RE",
    "BOX_3A_TAIL_RE",
    "BOX_3A_TITLE_RE",
    "BOX_3C_NEXT_LINE_RE",
    "BOX_3C_TAIL_RE",
    "BOX_3C_UNITS_RE",
    "BOX_3D_MARKET_VALUE_RE",
    "BOX_3D_TAIL_RE",
    "BOX_3G_EXCHANGE_RE",
    "COVER_HEADER_OR_SUBBOX_TERMS",
    "FORM144_NUMBERED_INSTRUCTION_RE",
    "NOTICE_DATE_LABEL_RE",
    "PHONE_RE",
    "PLAN_ADOPTION_ALT",
    "PLAN_ADOPTION_RE",
    "PLAN_ADOPTION_TERMS",
    "RELATIONSHIP_LABEL_RE",
    "RELATIONSHIP_TAIL_RE",
    "SEC_FILE_BARE_RE",
    "SEC_FILE_LABEL_RE",
    "SECURITY_CLASS_ALT",
    "SECURITY_CLASS_RE",
    "SECURITY_CLASS_TERMS",
    "is_cover_header_or_subbox_line",
    "is_form144_instruction_line",
    "form144_instruction_matches",
]
