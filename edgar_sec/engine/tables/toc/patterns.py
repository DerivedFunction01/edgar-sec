"""Tabular table-of-contents row patterns.
A contents row with a page suffix and a structural `PART`/`ITEM` heading both read as one prose line
but must not be unwrapped into one; the vocabulary lives here so both consumers share it.
"""

from __future__ import annotations

import re

from edgar_sec.foundation.text.patterns import PAGE_NUMBER_CORE, RE_DOT_LEADER

RE_PART_REFERENCE = re.compile(r"\bPART\s+(?:[IVXLCDM]+|\d+)\b", re.IGNORECASE)
RE_ITEM_REFERENCE = re.compile(r"\bITEM\s+\d+(?:\.\d+)*[A-Z]?\b", re.IGNORECASE)

RE_TOC_ITEM_ROW = re.compile(
    r"^\s*(?:[\|+]\s*)?ITEMS?\s+(\d{1,2})([A-Z])?\b", re.IGNORECASE
)
RE_TOC_LEADER = re.compile(rf"\s{RE_DOT_LEADER.pattern}\s")

RE_PAGE_SUFFIX = re.compile(
    rf"(?:\b[A-Z])?[\.\-\s]?{PAGE_NUMBER_CORE}(?:\s*[\|+])?\s*$",
    re.IGNORECASE,
)


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
    Covers dot-leader rows and leader-less rows opening with an ITEM reference and carrying a page suffix, the shape an HTML table TOC produces when columns replace leaders.
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
    Uses the shared patterns, so ``F-1`` and roman page tokens count.
    """
    stripped = line.strip().strip("|+")
    if not stripped:
        return False
    return bool(RE_DOT_LEADER.search(stripped) and RE_PAGE_SUFFIX.search(stripped))


__all__ = [
    "RE_ITEM_REFERENCE",
    "RE_PAGE_SUFFIX",
    "RE_PART_REFERENCE",
    "RE_TOC_ITEM_ROW",
    "RE_TOC_LEADER",
    "is_toc_row",
    "looks_like_toc_row",
    "looks_like_toc_tabular",
]
