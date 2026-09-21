"""Regex-based structural detection for SEC table boundaries."""

from __future__ import annotations

import re
from collections.abc import Callable

from defs.text.dates import COLUMN_YEAR_ROW_RE
from defs.text.patterns import RE_SENTENCE_TERMINAL, RE_SEPARATOR_LINE
from defs.text.reflow.features import _numeric_cell_starts

from .patterns import COLUMN_DASH_RULE_RE, UNITS_LABEL_RE

_RE_WIDE_COLUMN_GAP = re.compile(r"\s{3,}")


def is_header_prefix(lines: tuple[str, ...]) -> bool:
    """Return True if lines look like a statement title / column-header block.

    Accepts up to 6 nonblank lines to cover multi-line statement headers such as:
      CONSOLIDATED BALANCE SHEETS
      (in thousands, except share data)
      September 30,   September 30,
      2004            2003
      ----------      ----------
    """
    nonblank = tuple(line.strip() for line in lines if line.strip())
    if not nonblank or len(nonblank) > 6:
        return False
    if any(
        line.startswith(("<", "/", "o ", "- ", "* ", "PART ", "ITEM "))
        for line in nonblank
    ):
        return False
    for line in nonblank:
        if UNITS_LABEL_RE.search(line):
            continue
        if COLUMN_YEAR_ROW_RE.match(line):
            continue
        if COLUMN_DASH_RULE_RE.match(line):
            continue
        if RE_SENTENCE_TERMINAL.search(line) and len(line.split()) > 6:
            return False
        if len(line.split()) > 10:
            return False
    has_statement_title = any(
        line == line.upper() and any(character.isalpha() for character in line)
        for line in nonblank
    )
    return has_statement_title or any(
        "\t" in line
        or _RE_WIDE_COLUMN_GAP.search(line)
        or line[:1].isspace()
        or UNITS_LABEL_RE.search(line.strip())
        or COLUMN_YEAR_ROW_RE.match(line.strip())
        or COLUMN_DASH_RULE_RE.match(line.strip())
        for line in lines
    )


def is_structural_table_bridge(
    lines: tuple[str, ...],
    *,
    is_bridge_line: Callable[[str], bool] | None = None,
) -> bool:
    """Recognize section labels between parts of one aligned multi-section statement.

    Now also accepts standard financial statement subheadings (e.g.
    "LIABILITIES AND STOCKHOLDERS' EQUITY", "OPERATING ACTIVITIES") as valid
    bridges so that adjacent table halves are unified into one <TABLE>.
    """
    nonblank = tuple(line.strip() for line in lines if line.strip())
    if not nonblank or len(nonblank) > 6:
        return False
    for line in nonblank:
        numeric_starts = _numeric_cell_starts(line)
        if len(numeric_starts) >= 2:
            return False
        if RE_SEPARATOR_LINE.fullmatch(line):
            continue
        if is_bridge_line is not None and is_bridge_line(line):
            continue
        if len(line) > 80 or len(line.split()) > 12:
            return False
        if RE_SENTENCE_TERMINAL.search(line) and len(line.split()) > 6:
            return False
    return True


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
    nonblank = tuple(line.strip() for line in lines if line.strip())
    if not nonblank:
        return False
    has_separator = any(RE_SEPARATOR_LINE.fullmatch(line) for line in nonblank)
    has_multi_numeric = any(len(_numeric_cell_starts(line)) >= 2 for line in nonblank)
    has_total_keyword = bool(
        is_tail_line is not None and any(is_tail_line(line) for line in nonblank)
    )
    if has_separator and has_multi_numeric:
        return True
    return has_total_keyword and any(
        len(_numeric_cell_starts(line)) >= 1 for line in nonblank
    )


__all__ = [
    "is_header_prefix",
    "is_structural_table_bridge",
    "is_structural_table_tail",
]
