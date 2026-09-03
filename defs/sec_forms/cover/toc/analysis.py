"""TOC line analysis and normalization helpers."""

from __future__ import annotations

import re

from defs.sec_forms.cover.structure import (
    RE_ITEM_REFERENCE,
    RE_PART_REFERENCE,
    is_continuation_prose,
)
from defs.sec_forms.page_markers import RE_PAGE_SUFFIX, is_page_marker_line

from .patterns import (
    _RE_MULTI_SPACE,
    _RE_NON_ALPHANUM,
    RE_TOC_ITEM,
    RE_TOC_LEADER,
)


def normalize_for_matching(text: str) -> str:
    """Normalize text into clean lowercase single-spaced alphanumeric tokens."""
    if not text:
        return ""
    sanitized = _RE_NON_ALPHANUM.sub(" ", text.lower())
    return _RE_MULTI_SPACE.sub(" ", sanitized).strip()


def is_toc_row(line: str) -> bool:
    """Return whether ``line`` looks like a TOC row."""
    stripped = line.strip().strip("|+")
    if not stripped:
        return False
    if RE_TOC_LEADER.search(stripped) and RE_PAGE_SUFFIX.search(stripped):
        return bool(
            RE_PART_REFERENCE.search(stripped) or RE_ITEM_REFERENCE.search(stripped)
        )
    return False


def _line_offset(lines: list[str], line: int) -> int:
    return sum(len(value) + 1 for value in lines[:line])


def _row_lines(
    lines: list[str],
    start: int,
    limit: int,
    page_marker_lines: set[int] | None = None,
) -> list[int]:
    rows: list[int] = []
    for index in range(start, limit):
        line = lines[index].strip().strip("|+")
        if (
            not line
            or index in (page_marker_lines or set())
            or is_page_marker_line(line)
        ):
            continue
        if is_toc_row(line) or (
            RE_TOC_ITEM.match(line)
            and (RE_TOC_LEADER.search(line) or RE_PAGE_SUFFIX.search(line))
        ):
            rows.append(index)
    return rows


def score_block_toc_density(
    normalized_block: str,
    norm_toc_keywords: tuple[str, ...],
) -> tuple[int, tuple[str, ...]]:
    """Count matches of known TOC keywords in a normalized text block."""
    if not normalized_block or not norm_toc_keywords:
        return 0, ()
    hits = tuple(term for term in norm_toc_keywords if term in normalized_block)
    return len(hits), hits


def is_anachronistic_late_item(
    line: str,
    late_item_re: re.Pattern | None = None,
    norm_late_names: tuple[str, ...] = (),
) -> bool:
    """True if line matches a late item indicating TOC anachronism."""
    stripped = line.strip().strip("|+")
    if not stripped:
        return False
    if late_item_re is not None and late_item_re.match(stripped):
        return True
    if norm_late_names:
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
    "normalize_for_matching",
    "score_block_toc_density",
]
