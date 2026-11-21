"""Compiled regular expression patterns and vocabulary for ownership parsing."""

from __future__ import annotations

import re

from edgar_sec.domain.forms.families.ownership.evidence import (
    OWNERSHIP_FORM_NAMES,
    OWNERSHIP_PROSE_BOILERPLATE_RULE,
)
from edgar_sec.engine.forms.common.phrases import (
    PhraseMatch,
    compile_phrase_rules,
    match_phrase_rules,
)
from edgar_sec.foundation.regex.builder import build_alternation

OWNERSHIP_FORM_ALT = build_alternation(OWNERSHIP_FORM_NAMES, auto_escape=True)
OWNERSHIP_MASTHEAD_RE = re.compile(
    rf"(?i)securities\s+and\s+exchange\s+commission.*?(?:(?:{OWNERSHIP_FORM_ALT})|washington)"
)
OWNERSHIP_CONTINUATION_RE = re.compile(
    rf"(?i)(?:{OWNERSHIP_FORM_ALT})\s+continuation\b"
)
OWNERSHIP_PAGE_MARKER_RE = re.compile(
    rf"(?i)\b(?:{OWNERSHIP_FORM_ALT})\b|page\s+\d+|\(continued\)"
)

_COMPILED_PROSE_BOILERPLATE_RULE = compile_phrase_rules(
    (OWNERSHIP_PROSE_BOILERPLATE_RULE,)
)


def match_ownership_boilerplate(text: str) -> tuple[PhraseMatch, ...]:
    return match_phrase_rules(
        text,
        _COMPILED_PROSE_BOILERPLATE_RULE,
        family_id="ownership",
    )


def is_ownership_boilerplate(text: str) -> bool:
    return bool(match_ownership_boilerplate(text))


TABLE_TERMINATORS: tuple[str, ...] = (
    "/s/",
    "** signature",
    "signature of reporting person",
    "explanation of responses",
)

SUBHEADER_CELLS: frozenset[str] = frozenset(
    {
        "code",
        "v",
        "amount",
        "price",
        "(a) or (d)",
        "(a)",
        "(d)",
        "instr. 3",
        "instr. 4",
        "instr. 5",
        "instr. 8",
        "date",
        "title",
        "exercise",
        "conversion",
        "exercisable",
        "expiration",
        "following",
    }
)

INSTRUCTION_TOKEN_SETS: tuple[frozenset[str], ...] = tuple(
    frozenset(s.split())
    for s in (
        "filed pursuant section 16",
        "investment company act",
        "check box longer subject",
        "form obligations continue",
        "affirmative defense 10b5-1",
        "written trading plan",
        "reminder report separate line",
        "intentional misstatements criminal",
        "18 u.s.c 1001",
        "15 u.s.c 78ff",
        "omb approval",
        "3235-0287",
        "burden hours",
        "print type responses",
    )
)

HEADER_LABELS: tuple[str, ...] = (
    "title of security",
    "title of derivative",
    "title of class",
    "transaction date",
    "conversion or exercise",
    "date of earliest",
    "deemed execution date",
)

HEADER_SUB_KEYWORDS: tuple[str, ...] = (
    "instr.",
    "month/day",
    "end of month",
    "exercise",
    "conversion",
    "expiration",
    "following",
    "underlying",
)

EXACT_HEADER_CELLS: tuple[str, ...] = ("code", "v", "amount", "price", "(a) or (d)")

__all__ = [
    "EXACT_HEADER_CELLS",
    "HEADER_LABELS",
    "HEADER_SUB_KEYWORDS",
    "INSTRUCTION_TOKEN_SETS",
    "OWNERSHIP_CONTINUATION_RE",
    "OWNERSHIP_FORM_ALT",
    "OWNERSHIP_MASTHEAD_RE",
    "OWNERSHIP_PAGE_MARKER_RE",
    "SUBHEADER_CELLS",
    "TABLE_TERMINATORS",
    "is_ownership_boilerplate",
    "match_ownership_boilerplate",
]
