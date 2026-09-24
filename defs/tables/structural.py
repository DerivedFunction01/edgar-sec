"""Regex-based structural detection for SEC table boundaries."""

from __future__ import annotations

import re
from collections.abc import Callable

from defs.tables.tokens import numeric_cell_starts as _numeric_cell_starts
from defs.text.dates import COLUMN_YEAR_ROW_RE
from defs.text.patterns import RE_SENTENCE_TERMINAL, RE_SEPARATOR_LINE
from defs.text.tokens import (
    is_bullet_line,
    is_list_or_bullet_marker,
    is_ordered_marker_prefix,
    is_wrapped_marker_prefix,
)

from .patterns import (
    COLUMN_DASH_RULE_RE,
    PERIOD_SUBHEADING_RE,
    UNITS_LABEL_RE,
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
        has_alpha = False
        for char in cleaned:
            if char.isalpha():
                has_alpha = True
                break
        if has_alpha:
            valid_words += 1
            if cleaned[0].isupper():
                capitalized += 1

    return valid_words >= 2 and capitalized >= 2 and capitalized / valid_words >= 0.6


def is_header_prefix(lines: tuple[str, ...]) -> bool:
    """Return whether lines immediately preceding a table block form a valid table header."""
    nonblank_count = 0
    has_statement_title = False
    has_special_pattern = False
    has_formatting = False

    for line in lines:
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
    lines: tuple[str, ...],
    *,
    is_bridge_line: Callable[[str], bool] | None = None,
) -> bool:
    """Recognize heading-shaped labels between parts of one statement.

    Longer or nonstandard labels must be approved by the owning phase's explicit
    ``is_bridge_line`` callback; short narrative sentences are not bridges.
    """
    nonblank_count = 0
    for line in lines:
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
    lines: tuple[str, ...],
    *,
    is_tail_line: Callable[[str], bool] | None = None,
) -> bool:
    """Recognize a final aligned total / double-underline that follows a statement body.

    Accepts:
    - Rows that contain a known total keyword AND numeric cells, or
    - Double-underline separator rows (===  ===) adjacent to numeric rows.
    """
    has_separator = False
    has_multi_numeric = False
    has_numeric = False
    has_total_keyword = False
    has_nonblank = False

    for line in lines:
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
    "is_header_prefix",
    "is_structural_table_bridge",
    "is_structural_table_tail",
]
