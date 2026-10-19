from __future__ import annotations

import re

from edgar_sec.engine.forms.common.statutory import (
    HEADER_LEAK_RE,
    STATUTORY_PAGE_ARTIFACT_RE,
)
from edgar_sec.foundation.regex.builder import build_alternation
from edgar_sec.engine.forms.beneficial_ownership.vocabulary import COVER_LABEL_PHRASES

_CUSIP_SHORT_RE = re.compile(r"(?i)^[0-9A-Z*@#]{8}$")
_CUSIP_UNAVAILABLE_NOT_ALT = build_alternation(
    ("AVAILABLE", "APPLICABLE", "PROVIDED"), auto_escape=True, compact=True
)
_CUSIP_UNAVAILABLE_ALT = build_alternation(
    (r"NONE\.?", r"N/?A\.?", rf"NOT\s+(?:{_CUSIP_UNAVAILABLE_NOT_ALT})", "UNKNOWN"),
    compact=False,
)
_CUSIP_UNAVAILABLE_RE = re.compile(rf"(?i)^\s*(?:{_CUSIP_UNAVAILABLE_ALT})\s*$")
_CUSIP_PAGE_RESIDUE_RE = re.compile(r"(?i)\bSCHEDULE\s*13[DG]\b|\bPAGE\s*\d+\b")
_ANY_NUMBER_RE = re.compile(r"\d")
_FUND_CODE_SPLIT_RE = re.compile(r"[^A-Za-z0-9]+")
_NUMERIC_FOOTNOTE_RE = re.compile(r"(?i)^\s*\d[\d,]*(?:\.\d+)?\s*\[\d+\]\s*$")
_QUALIFIED_NUMERIC_PHRASES = (
    "shares of",
    "shares (",
    "shares(",
    "shares *",
    "shares issuable",
    "shares held",
    "warrants",
    "based on",
    "approximately",
    "approx.",
    "less than",
    "common",
    "common stock",
    "preferred stock",
    "represented by",
    "including",
)
_COVER_LABEL_LEAK_ALT = build_alternation(
    (*COVER_LABEL_PHRASES,),
    auto_escape=True,
    compact=True,
)
_COVER_LABEL_LEAK_RE = re.compile(_COVER_LABEL_LEAK_ALT, re.IGNORECASE)
_SEPARATOR_RUN_RE = re.compile(r"[-_]{2,}|(?:\s*[:|]\s*){2,}")
_PERSON_WITH_LABEL_RE = re.compile(r"(?i)\bPERSON\s*[:|]\s*WITH\b")
_COVER_ITEM_HEADING_RE = re.compile(r"(?i)\bITEM\s+\d+[A-Z]?\s*[.:]\s+[A-Z]")
_ROW_PREFIX_RE = {
    field: re.compile(rf"(?i)^\s*{row}\s+(?=\d|PERSON\b|SHARES\b)")
    for field, row in {
        "soleVotingPower": 7,
        "sharedVotingPower": 8,
        "soleDispositivePower": 9,
        "sharedDispositivePower": 10,
        "aggregateAmountOwned": 11,
        "percentOfClass": 13,
    }.items()
}
_POWER_LAYOUT_LEAK_ALT = build_alternation(
    (
        r"(?:PERSON\s+)?WITH\b",
        r"\d{1,2}\s+PERSON\b",
        r"BY\s+EACH\s+PERSON\b",
    ),
    compact=False,
)
_POWER_LAYOUT_LEAK_RE = re.compile(rf"(?i)^\s*(?:{_POWER_LAYOUT_LEAK_ALT})")
_POWER_LAYOUT_TRAILING_WITH_RE = re.compile(r"(?i)\bWITH\s*$")
_NEVER_MATCH_RE = re.compile(r"(?!)")
_PARSED_FIELD_BOILERPLATE_ALT = build_alternation(
    (
        "I.R.S. IDENTIFICATION",
        "CHECK THE APPROPRIATE BOX",
        "CHECK APPROPRIATE BOX",
        "TYPE OF REPORTING PERSON",
        "SCHEDULE 13D",
        "SCHEDULE 13G",
        "SECURITIES AND EXCHANGE COMMISSION",
        "UNDER THE SECURITIES EXCHANGE ACT",
        "SEE INSTRUCTIONS",
        "SIGNATURE",
        "ITEM 1.",
        "ITEM 2.",
        "ITEM 3.",
        "ITEM 4.",
        "ITEM 5.",
        "ITEM 6.",
        "ITEM 7.",
        "PERSONS WHO ARE TO RESPOND",
        "COLLECTION OF INFORMATION",
    ),
    auto_escape=True,
    compact=True,
)
_PARSED_FIELD_BOILERPLATE_RE = re.compile(
    rf"(?i)(?<![A-Z])(?:{_PARSED_FIELD_BOILERPLATE_ALT})(?![A-Z])"
)


def is_eight_character_cusip(value: str) -> bool:
    return bool(_CUSIP_SHORT_RE.fullmatch(value))


def is_unavailable_cusip(value: str) -> bool:
    return bool(_CUSIP_UNAVAILABLE_RE.fullmatch(value))


def cusip_page_residue_match(value: str) -> re.Match[str] | None:
    return _CUSIP_PAGE_RESIDUE_RE.search(value)


def two_character_codes(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    codes: list[str] = []
    for token in _FUND_CODE_SPLIT_RE.split(value):
        if (
            len(token) == 2
            and (token.isupper() or token.isdigit())
            and token not in codes
        ):
            codes.append(token)
    return tuple(codes)


def has_descriptive_numeric_qualifier(value: str) -> bool:
    lowered = value.casefold()
    return (
        bool(_NUMERIC_FOOTNOTE_RE.fullmatch(value))
        or bool(_ANY_NUMBER_RE.search(value))
        and any(phrase in lowered for phrase in _QUALIFIED_NUMERIC_PHRASES)
    )


def cover_field_has_layout_residue(field: str, value: str) -> bool:
    row_prefix = _ROW_PREFIX_RE.get(field, _NEVER_MATCH_RE)
    return bool(
        HEADER_LEAK_RE.search(value)
        or _COVER_LABEL_LEAK_RE.search(value)
        or _SEPARATOR_RUN_RE.search(value)
        or _PERSON_WITH_LABEL_RE.search(value)
        or _COVER_ITEM_HEADING_RE.search(value)
        or _POWER_LAYOUT_LEAK_RE.search(value)
        or _POWER_LAYOUT_TRAILING_WITH_RE.search(value)
        or row_prefix.search(value)
    )


def parsed_field_boilerplate_match(value: str) -> re.Match[str] | None:
    for pattern in (STATUTORY_PAGE_ARTIFACT_RE, HEADER_LEAK_RE):
        match = pattern.search(value)
        if match is not None:
            return match
    return _PARSED_FIELD_BOILERPLATE_RE.search(value)


__all__ = [
    "cover_field_has_layout_residue",
    "cusip_page_residue_match",
    "has_descriptive_numeric_qualifier",
    "is_eight_character_cusip",
    "is_unavailable_cusip",
    "parsed_field_boilerplate_match",
    "two_character_codes",
]
