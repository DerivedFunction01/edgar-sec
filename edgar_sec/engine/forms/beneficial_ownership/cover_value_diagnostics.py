from __future__ import annotations

import re

from edgar_sec.engine.forms.common.statutory import HEADER_LEAK_RE
from edgar_sec.foundation.regex.builder import build_alternation

_CUSIP_SHORT_RE = re.compile(r"(?i)^[0-9A-Z*@#]{8}$")
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
    (
        "name of reporting person",
        "names of reporting persons",
        "check the appropriate box",
        "source of funds",
        "sec use only",
        "check if disclosure of legal proceedings",
        "citizenship or place of organization",
        "sole voting power",
        "shared voting power",
        "sole dispositive power",
        "shared dispositive power",
        "aggregate amount beneficially owned",
        "owned by",
        "owned by each reporting person",
        "person with",
        "identification nos. of above persons",
        "i.d. no.",
        "percent of class represented",
        "type of reporting person",
        "see instructions",
        "pursuant to items",
        "by each person",
        "voting power",
        "dispositive power",
        "shares beneficially owned",
    ),
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


def is_eight_character_cusip(value: str) -> bool:
    return bool(_CUSIP_SHORT_RE.fullmatch(value))


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


__all__ = [
    "cover_field_has_layout_residue",
    "has_descriptive_numeric_qualifier",
    "is_eight_character_cusip",
    "two_character_codes",
]
