"""TOC line analysis and normalization helpers.

The row predicates themselves — ``is_toc_row``, ``looks_like_toc_row``, and
``looks_like_toc_tabular`` — live in
:mod:`edgar_sec.engine.tables.toc.patterns`, because table classification
refuses the same rows and both sides must agree on what a TOC row is. This
module adds the block-level analysis the cover stage needs: row gathering under
a rendered table, keyword-density scoring, and the late-item anachronism test.
"""

from __future__ import annotations

import re
from itertools import pairwise

from edgar_sec.engine.document.page_markers.detector import is_page_marker_line
from edgar_sec.engine.forms.cover.structure import (
    is_continuation_prose,
)
from edgar_sec.engine.tables.toc.patterns import (
    RE_TOC_ITEM_ROW,
    is_toc_row,
    looks_like_toc_row,
    looks_like_toc_tabular,
)

from .patterns import (
    _RE_MULTI_SPACE,
    _RE_NON_ALPHANUM,
    RE_TOC_PART_ROW,
)

_RE_TABLE_TOC_ROW = re.compile(r"^(?P<label>.+?)(?P<gap>\s{2,})(?P<page>\d{1,4})\s*$")


def normalize_for_matching(text: str) -> str:
    """Normalize text into clean lowercase single-spaced alphanumeric tokens."""
    if not text:
        return ""
    sanitized = _RE_NON_ALPHANUM.sub(" ", text.lower())
    return _RE_MULTI_SPACE.sub(" ", sanitized).strip()


def _line_offset(lines: list[str], line: int) -> int:
    return sum(len(value) + 1 for value in lines[:line])


def _row_lines(
    lines: list[str],
    start: int,
    limit: int,
    page_marker_lines: set[int] | None = None,
    max_gap: int = 5,
    max_span: int = 250,
) -> list[int]:
    rows: list[int] = []
    consecutive_prose = 0
    for index in range(start, min(limit, start + max_span)):
        line = lines[index].strip().strip("|+")
        if (
            not line
            or index in (page_marker_lines or set())
            or is_page_marker_line(line)
        ):
            continue
        if looks_like_toc_row(line):
            rows.append(index)
            consecutive_prose = 0
        else:
            if rows:
                consecutive_prose += 1
                if consecutive_prose >= max_gap:
                    break
    return rows


def _table_toc_rows(lines: list[str], start: int, limit: int) -> list[int]:
    """Return aligned, monotonic TOC rows from a rendered tagged table.

    HTML table rendering replaces dot leaders with column whitespace, and many
    rows are subsection labels rather than ``ITEM`` rows.  Keep this broader
    rule table-scoped and require a real TOC signal before accepting it.
    """
    candidates: list[tuple[int, int, str]] = []
    for index in range(start, min(limit, start + 250)):
        line = lines[index].strip().strip("|+")
        if not line or is_page_marker_line(line):
            continue
        match = _RE_TABLE_TOC_ROW.match(line)
        if match is None:
            continue
        candidates.append((index, int(match.group("page")), match.group("label")))

    if not candidates or not any(
        RE_TOC_ITEM_ROW.match(label) or RE_TOC_PART_ROW.match(label)
        for _, _, label in candidates
    ):
        return []

    page_columns = [
        _RE_TABLE_TOC_ROW.match(lines[index].strip().strip("|+")).start("page")
        for index, _, _ in candidates
    ]
    if max(page_columns) - min(page_columns) > 2:
        return []
    pages = [page for _, page, _ in candidates]
    if any(current < previous for previous, current in pairwise(pages)):
        return []
    return [index for index, _, _ in candidates]


def score_block_toc_density(
    normalized_block: str,
    norm_toc_keywords: tuple[str, ...] | object,
) -> tuple[int, tuple[str, ...]]:
    """Count matches of known TOC keywords in a normalized text block."""
    if not normalized_block:
        return 0, ()
    if hasattr(norm_toc_keywords, "find_matches"):
        matches = norm_toc_keywords.find_matches(normalized_block)
        hits = tuple(
            sorted(
                {
                    m.term
                    for m in matches
                    if m.category == "toc_keywords" and not m.is_exclusion
                }
            )
        )
        return len(hits), hits
    if not norm_toc_keywords:
        return 0, ()
    hits = tuple(term for term in norm_toc_keywords if term in normalized_block)
    return len(hits), hits


def is_anachronistic_late_item(
    line: str,
    late_item_re: re.Pattern | None = None,
    norm_late_names: tuple[str, ...] | object = (),
) -> bool:
    """True if line matches a late item indicating TOC anachronism."""
    stripped = line.strip().strip("|+")
    if not stripped:
        return False
    if late_item_re is not None and late_item_re.match(stripped):
        return True
    if hasattr(norm_late_names, "has_any"):
        norm_line = normalize_for_matching(stripped)
        if len(stripped) <= 120 and not is_continuation_prose(stripped):
            return norm_late_names.has_any(norm_line, ["late_names"])
    elif norm_late_names:
        norm_line = normalize_for_matching(stripped)
        if (
            len(stripped) <= 120
            and not is_continuation_prose(stripped)
            and any(name in norm_line for name in norm_late_names)
        ):
            return True
    return False


__all__ = [
    "is_anachronistic_late_item",
    "is_toc_row",
    "looks_like_toc_row",
    "looks_like_toc_tabular",
    "normalize_for_matching",
    "score_block_toc_density",
]
