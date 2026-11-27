"""Date vocabulary and compiled date patterns for SEC filings."""

from __future__ import annotations

import re

from edgar_sec.foundation.regex.builder import build_alternation


MONTH_NAMES = (
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
)


MONTH_ALIASES: tuple[tuple[str, ...], ...] = (
    ("january", "jan", "jan."),
    ("february", "feb", "feb."),
    ("march", "mar", "mar."),
    ("april", "apr", "apr."),
    ("may",),
    ("june", "jun", "jun."),
    ("july", "jul", "jul."),
    ("august", "aug", "aug."),
    ("september", "sep", "sept", "sep.", "sept."),
    ("october", "oct", "oct."),
    ("november", "nov", "nov."),
    ("december", "dec", "dec."),
)


_MONTH_NAME_TO_INDEX: dict[str, int] = {}


_MONTH_PATTERN_PARTS: list[str] = []


for index, aliases in enumerate(MONTH_ALIASES, start=1):
    _MONTH_NAME_TO_INDEX.update({alias: index for alias in aliases})
    _MONTH_PATTERN_PARTS.extend(aliases)


MONTH_PATTERN = build_alternation(_MONTH_PATTERN_PARTS, auto_escape=True, compact=True)


MONTH_RE = re.compile(rf"(?i){MONTH_PATTERN}")


MONTH_NAME_RE = re.compile(rf"(?i)^(?:{MONTH_PATTERN})$")


MONTH_WORD_RE = re.compile(rf"\b(?:{MONTH_PATTERN})\b", re.IGNORECASE)


QUARTER_LABEL_RE = re.compile(r"\bQ[1-4]\b", re.IGNORECASE)


ORDINAL_SUFFIX_PATTERN = build_alternation(
    [r"st", r"nd", r"rd", r"th"], auto_escape=True
)


ORDINAL_SUFFIX_RE = re.compile(rf"(?i)(\d+)(?:{ORDINAL_SUFFIX_PATTERN})\b")


MONTH_SUFFIX_RE = re.compile(rf"(?i)(?:{MONTH_PATTERN})\s*$")


YEAR_TOKEN_PATTERN = build_alternation(
    [r"19[0-9]{2}", r"[2-9][0-9]{3}"], auto_escape=False
)


YEAR_TOKEN_RE = re.compile(rf"^\b({YEAR_TOKEN_PATTERN})\b$")


YEAR_TOKEN_SEARCH_RE = re.compile(rf"\b(?:{YEAR_TOKEN_PATTERN})\b")


# Strict variant: full month names only — the frozen Step 3
# instrument's dated-row language, not a general recognizer.
STRICT_MONTH_PATTERN = "|".join(MONTH_NAMES)


YEAR_IN_TEXT_RE = re.compile(r"\b(\d{4})\b")


NUMERIC_YEAR_RE = re.compile(r"\b(\d{2,4})\b")


NUMERIC_DATE_RE = re.compile(r"\b\d{1,2}[-/]\d{1,2}[-/]\d{2,4}\b")


ISO_DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")


TABLE_YEAR_RE = re.compile(
    build_alternation(
        [r"(?:\d{1,2}/)+(\d{2,4})", r"\b(\d{4})\b", r"['’](\d{2})\b"],
        auto_escape=False,
    )
)


_DATE_TOKEN_PAT = rf"(?:{MONTH_PATTERN})\s+\d{{1,2}},?\s+{YEAR_TOKEN_PATTERN}"


RE_FULL_DATE = re.compile(rf"\b(?:{_DATE_TOKEN_PAT})\b", re.IGNORECASE)


_DATE_OR_YEAR_PAT = build_alternation(
    [_DATE_TOKEN_PAT, YEAR_TOKEN_PATTERN], auto_escape=False, compact=False
)


RE_DATE_OR_YEAR = re.compile(rf"\b(?:{_DATE_OR_YEAR_PAT})\b", re.IGNORECASE)


_MONTH_NAME_PATTERN = build_alternation(MONTH_NAMES, auto_escape=True, compact=True)


# A lone full-date label ("December 31, 2023"), whole string: the
# dated-stub shape rollforward walks read as a balance anchor.
FULL_DATE_STUB_RE = re.compile(rf"(?i)^(?:{_MONTH_NAME_PATTERN}) \d{{1,2}}, \d{{4}}$")


# Full month names only, as a word: the names-only counterpart of
# MONTH_WORD_RE (which carries the abbreviated aliases).
MONTH_NAME_WORD_RE = re.compile(rf"\b(?:{_MONTH_NAME_PATTERN})\b", re.IGNORECASE)


_DAY_FIRST_DATE_PAT = (
    rf"\d{{1,2}}(?:{ORDINAL_SUFFIX_PATTERN})?\s+(?:{MONTH_PATTERN}),?\s+"
    rf"{YEAR_TOKEN_PATTERN}"
)


_ISO_DATE_PAT = r"\d{4}-\d{2}-\d{2}"


_NUMERIC_DATE_PAT = r"\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}"


# Every evidence-backed full-date spelling in one recognizer
# (format invariance): Month-first, day-first, ISO, and numeric
# slash/dash/dot. Validation runs through the parse core, whose
# 2-digit expansion is the settled rolling span.
FULL_DATE_ANY_RE = re.compile(
    rf"\b(?:{_DATE_TOKEN_PAT}|{_DAY_FIRST_DATE_PAT}|{_ISO_DATE_PAT}|"
    rf"{_NUMERIC_DATE_PAT})\b",
    re.IGNORECASE,
)


_Q_TOKEN_PAT = rf"Q[1-4]\s+{YEAR_TOKEN_PATTERN}"


_PERIOD_TOKEN_PAT = build_alternation(
    [YEAR_TOKEN_PATTERN, _Q_TOKEN_PAT, _DATE_TOKEN_PAT],
    auto_escape=False,
    compact=False,
)


_PERIOD_HEADER_SUFFIX_PAT = build_alternation(
    [_PERIOD_TOKEN_PAT, MONTH_PATTERN, r"Q[1-4]"],
    auto_escape=False,
    compact=False,
)


COLUMN_YEAR_ROW_RE = re.compile(
    rf"^\s*(?:{_PERIOD_TOKEN_PAT})(?:\s+(?:{_PERIOD_HEADER_SUFFIX_PAT}).*)?\s*$",
    re.IGNORECASE,
)


_PERIOD_SPAN_WORDS = build_alternation(
    [
        "three months",
        "six months",
        "nine months",
        "fiscal year",
        "fiscal",
        "year",
        "years",
        "quarter",
        "quarters",
        "period",
        "periods",
    ],
    auto_escape=True,
    compact=True,
)


_PERIOD_SUBHEADING_PATTERNS = [
    rf"(?:{_PERIOD_SPAN_WORDS})\s+(?:ended\s+)?{YEAR_TOKEN_PATTERN}",
    rf"(?:{_PERIOD_SPAN_WORDS})\s+(?:ended\s+)?Q[1-4]",
    rf"Q[1-4]\s+{YEAR_TOKEN_PATTERN}",
]


PERIOD_SUBHEADING_PAT = build_alternation(
    _PERIOD_SUBHEADING_PATTERNS, auto_escape=False, compact=False
)


PERIOD_SUBHEADING_RE = re.compile(
    rf"^\s*(?:{PERIOD_SUBHEADING_PAT})\s*:?\s*$", re.IGNORECASE
)


# Period-caption forms. PERIOD_ENDED_PAT is the composition fragment for
# caption-anchored variants; the compiled forms below are the search and
# capture shapes consumers anchor on, each kept to its attested wording.
PERIOD_ENDED_PAT = r"(?:period|fiscal year|quarter) ended"


PERIOD_ENDED_RE = re.compile(r"(?:period|fiscal year) ended\s+", re.IGNORECASE)


REPORTING_PERIOD_FROM_PAT = r"reporting period from\s+"


REPORTING_PERIOD_CAPTION_RE = re.compile(
    r"date of reporting period\s*:?\s*", re.IGNORECASE
)


REPORTING_PERIOD_LABEL_RE = re.compile(r"reporting period:\s*(.*)", re.IGNORECASE)


REPORTING_PERIOD_VALUE_RE = re.compile(
    r"date of reporting period:\s*(.+)", re.IGNORECASE
)


REPORT_QUARTER_ENDED_RE = re.compile(
    r"Report for the (?:Calendar Year or )?Quarter Ended:?\s*(.+)", re.IGNORECASE
)


def month_name_to_index(value: str) -> int | None:
    """Map a month name or alias to its 1-based integer index."""
    return _MONTH_NAME_TO_INDEX.get(value.strip().lower())


__all__ = [
    "COLUMN_YEAR_ROW_RE",
    "MONTH_ALIASES",
    "MONTH_NAMES",
    "MONTH_NAME_RE",
    "MONTH_PATTERN",
    "MONTH_RE",
    "MONTH_WORD_RE",
    "QUARTER_LABEL_RE",
    "MONTH_SUFFIX_RE",
    "ISO_DATE_RE",
    "NUMERIC_DATE_RE",
    "NUMERIC_YEAR_RE",
    "ORDINAL_SUFFIX_PATTERN",
    "ORDINAL_SUFFIX_RE",
    "PERIOD_ENDED_PAT",
    "PERIOD_ENDED_RE",
    "PERIOD_SUBHEADING_PAT",
    "PERIOD_SUBHEADING_RE",
    "REPORTING_PERIOD_CAPTION_RE",
    "REPORTING_PERIOD_FROM_PAT",
    "REPORTING_PERIOD_LABEL_RE",
    "REPORTING_PERIOD_VALUE_RE",
    "REPORT_QUARTER_ENDED_RE",
    "RE_DATE_OR_YEAR",
    "RE_FULL_DATE",
    "FULL_DATE_STUB_RE",
    "STRICT_MONTH_PATTERN",
    "TABLE_YEAR_RE",
    "YEAR_IN_TEXT_RE",
    "YEAR_TOKEN_PATTERN",
    "YEAR_TOKEN_RE",
    "YEAR_TOKEN_SEARCH_RE",
    "month_name_to_index",
]
