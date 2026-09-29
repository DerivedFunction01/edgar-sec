"""Regex-based structural detection for SEC table boundaries."""

from __future__ import annotations

import re
from collections.abc import Callable

from edgar_sec.engine.tables.numeric_cells import (
    numeric_cell_starts as _numeric_cell_starts,
)
from edgar_sec.foundation.regex.builder import build_alternation
from edgar_sec.foundation.text.dates import MONTH_PATTERN
from edgar_sec.foundation.text.patterns import RE_SENTENCE_TERMINAL, RE_SEPARATOR_LINE
from edgar_sec.foundation.text.tokens import (
    is_bullet_line,
    is_list_or_bullet_marker,
    is_ordered_marker_prefix,
    is_wrapped_marker_prefix,
)

COLUMN_DASH_RULE_RE = re.compile(r"^\s*[-=]{1,25}(?:\s+[-=]{1,25}){1,}\s*$")

_PERIOD_TERMS = build_alternation(
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
    ]
)
PERIOD_SUBHEADING_RE = re.compile(
    rf"^\s*(?:{_PERIOD_TERMS}\s+(?:ended\s+)?(?:\d{{4}}|Q[1-4])|Q[1-4]\s+\d{{4}})\s*:?\s*$",
    re.IGNORECASE,
)

_UNITS_QUALIFIER = build_alternation(["dollars", "amounts?", "shares?"])
_UNITS_SCALE = build_alternation(
    [
        "thousands?",
        "millions?",
        "billions?",
        "trillions?",
        "shares?",
        "dollars?",
        "percent(?:age)?",
    ]
)
UNITS_LABEL_RE = re.compile(
    rf"\(\s*(?:{_UNITS_QUALIFIER}\s+)?in\s+{_UNITS_SCALE}[^)]*\)",
    re.IGNORECASE,
)

_YEAR_OR_QUARTER = build_alternation([r"\d{4}", r"Q[1-4]\s+\d{4}"])
_YEAR_ROW_TAIL = build_alternation([_YEAR_OR_QUARTER, MONTH_PATTERN, "Q[1-4]"])
COLUMN_YEAR_ROW_RE = re.compile(
    rf"^\s*{_YEAR_OR_QUARTER}(?:\s+{_YEAR_ROW_TAIL}.*)?\s*$",
    re.IGNORECASE,
)

_RE_WIDE_COLUMN_GAP = re.compile(r"\s{3,}")
_HEADING_STOP_WORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "as",
        "at",
        "by",
        "for",
        "from",
        "in",
        "of",
        "on",
        "or",
        "the",
        "to",
    }
)
_TAG_OR_SECTION_PREFIXES = ("<", "/", "PART ", "ITEM ", "NOTE ", "Note ")


def _is_heading_like_bridge_line(line: str) -> bool:
    words = line.split()
    if not words or len(words) > 6 or len(line) > 80:
        return False
    if line.isupper():
        return True
    if PERIOD_SUBHEADING_RE.match(line):
        return True
    if line.endswith(":") and len(words) <= 4:
        return True
    if RE_SENTENCE_TERMINAL.search(line):
        return False

    valid_words = 0
    capitalized = 0
    for word in words:
        cleaned = word.strip("()[],:;")
        if not cleaned or cleaned.lower() in _HEADING_STOP_WORDS:
            continue
        has_alpha = any(char.isalpha() for char in cleaned)
        if has_alpha:
            valid_words += 1
            if cleaned[0].isupper():
                capitalized += 1

    return valid_words >= 2 and capitalized >= 2 and capitalized / valid_words >= 0.6


def is_header_prefix(lines: str | tuple[str, ...] | list[str]) -> bool:
    """Return whether lines immediately preceding a table block form a valid table header."""
    line_seq = (lines,) if isinstance(lines, str) else tuple(lines)
    nonblank_count = 0
    has_statement_title = False
    has_special_pattern = False
    has_formatting = False

    for line in line_seq:
        if "\t" in line or line[:1].isspace() or bool(_RE_WIDE_COLUMN_GAP.search(line)):
            has_formatting = True

        stripped = line.strip()
        if not stripped:
            continue

        nonblank_count += 1
        if nonblank_count > 6:
            return False

        words = stripped.split()
        word_count = len(words)
        if word_count > 10:
            return False
        if word_count >= 4 and stripped.endswith(":"):
            return False
        if word_count > 6 and RE_SENTENCE_TERMINAL.search(stripped):
            return False

        if (
            COLUMN_DASH_RULE_RE.match(stripped)
            or RE_SEPARATOR_LINE.fullmatch(stripped)
            or UNITS_LABEL_RE.search(stripped)
            or COLUMN_YEAR_ROW_RE.match(stripped)
            or PERIOD_SUBHEADING_RE.match(stripped)
        ):
            has_special_pattern = True
            continue

        if (
            stripped.startswith(_TAG_OR_SECTION_PREFIXES)
            or is_bullet_line(stripped)
            or is_ordered_marker_prefix(stripped)
            or is_wrapped_marker_prefix(stripped)
            or is_list_or_bullet_marker(stripped)
        ):
            return False

        if not has_statement_title and stripped.isupper():
            has_statement_title = True

    if nonblank_count == 0:
        return False

    return has_statement_title or has_special_pattern or has_formatting


def is_structural_table_bridge(
    lines: str | tuple[str, ...] | list[str],
    *,
    is_bridge_line: Callable[[str], bool] | None = None,
) -> bool:
    """Recognize heading-shaped labels between parts of one statement."""
    line_seq = (lines,) if isinstance(lines, str) else tuple(lines)
    nonblank_count = 0
    for line in line_seq:
        stripped = line.strip()
        if not stripped:
            continue
        nonblank_count += 1
        if nonblank_count > 6:
            return False
        if len(_numeric_cell_starts(stripped)) >= 2:
            return False
        if RE_SEPARATOR_LINE.fullmatch(stripped):
            continue
        if is_bridge_line is not None and is_bridge_line(stripped):
            continue
        if not _is_heading_like_bridge_line(stripped):
            return False
    return nonblank_count > 0


def is_structural_table_tail(
    lines: str | tuple[str, ...] | list[str],
    *,
    is_tail_line: Callable[[str], bool] | None = None,
) -> bool:
    """Recognize a final aligned total / double-underline that follows a statement body."""
    line_seq = (lines,) if isinstance(lines, str) else tuple(lines)
    has_separator = False
    has_multi_numeric = False
    has_numeric = False
    has_total_keyword = False
    has_nonblank = False

    for line in line_seq:
        stripped = line.strip()
        if not stripped:
            continue
        has_nonblank = True
        if not has_separator and RE_SEPARATOR_LINE.fullmatch(stripped):
            has_separator = True
        if (
            not has_total_keyword
            and is_tail_line is not None
            and is_tail_line(stripped)
        ):
            has_total_keyword = True

        numeric_count = len(_numeric_cell_starts(stripped))
        if numeric_count >= 1:
            has_numeric = True
            if numeric_count >= 2:
                has_multi_numeric = True

        if has_separator and has_multi_numeric:
            return True

    if not has_nonblank:
        return False
    return has_total_keyword and has_numeric


__all__ = [
    "COLUMN_DASH_RULE_RE",
    "COLUMN_YEAR_ROW_RE",
    "PERIOD_SUBHEADING_RE",
    "UNITS_LABEL_RE",
    "is_header_prefix",
    "is_structural_table_bridge",
    "is_structural_table_tail",
]
