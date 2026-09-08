"""TOC line analysis and normalization helpers."""

from __future__ import annotations

import re

from defs.sec_forms.cover.structure import (
    RE_ITEM_REFERENCE,
    RE_PART_REFERENCE,
    is_continuation_prose,
)
from defs.sec_forms.page_markers import RE_PAGE_SUFFIX, is_page_marker_line
from defs.text.patterns import RE_DOT_LEADER

from .patterns import (
    _RE_MULTI_SPACE,
    _RE_NON_ALPHANUM,
    RE_TOC_ITEM_ROW,
    RE_TOC_LEADER,
)


def normalize_for_matching(text: str) -> str:
    """Normalize text into clean lowercase single-spaced alphanumeric tokens."""
    if not text:
        return ""
    sanitized = _RE_NON_ALPHANUM.sub(" ", text.lower())
    return _RE_MULTI_SPACE.sub(" ", sanitized).strip()


def is_toc_row(line: str) -> bool:
    """Return whether ``line`` looks like a dot-leader TOC row."""
    stripped = line.strip().strip("|+")
    if not stripped:
        return False
    if RE_TOC_LEADER.search(stripped) and RE_PAGE_SUFFIX.search(stripped):
        return bool(
            RE_PART_REFERENCE.search(stripped) or RE_ITEM_REFERENCE.search(stripped)
        )
    return False


def looks_like_toc_row(line: str) -> bool:
    """Return whether ``line`` matches any TOC row form.

    Covers dot-leader rows (:func:`is_toc_row`) and leader-less rows that begin
    with an ITEM reference and carry a trailing page suffix — the shape HTML
    table TOCs produce when columns replace dot leaders. Old ASCII filings use
    dot leaders; HTML TOCs live inside ``<TABLE>`` blocks whose rendered rows
    keep the page suffix as cell text.
    """
    stripped = line.strip().strip("|+")
    if not stripped:
        return False
    if is_toc_row(stripped):
        return True
    return bool(
        RE_TOC_ITEM_ROW.match(stripped)
        and (RE_TOC_LEADER.search(stripped) or RE_PAGE_SUFFIX.search(stripped))
    )


def looks_like_toc_tabular(line: str) -> bool:
    """Return whether a line is dot-leader tabular content with a page token.

    Uses the shared dot-leader and page-suffix patterns, so digits, namespaced
    financial-statement pages (``F-1``), and roman numerals (``xii``) all count.
    """
    stripped = line.strip().strip("|+")
    if not stripped:
        return False
    return bool(RE_DOT_LEADER.search(stripped) and RE_PAGE_SUFFIX.search(stripped))


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
    "normalize_for_matching",
    "score_block_toc_density",
]
