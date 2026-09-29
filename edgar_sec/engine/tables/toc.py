"""Structural helpers and regex patterns for table-of-contents detection."""

from __future__ import annotations

import re

from edgar_sec.foundation.text.patterns import RE_DOT_LEADER, RE_PAGE_NUMBER_SUFFIX

RE_PART_REFERENCE = re.compile(r"\bPART\s+(?:[IVXLCDM]+|\d+)\b", re.IGNORECASE)
RE_ITEM_REFERENCE = re.compile(r"\bITEM\s+\d+(?:\.\d+)*[A-Z]?\b", re.IGNORECASE)
RE_TOC_ITEM_ROW = re.compile(r"^\s*(?:ITEM|PART)\b.*?(?:\d+|[ivxlc]+\b)", re.IGNORECASE)
RE_TOC_LEADER = re.compile(r"\.{3,}|[-_]{4,}")
RE_TOC_PART_TEXT = re.compile(r"\bPART\s+[IVXLCDM]+\b", re.IGNORECASE)
PART_HEADING_RE = re.compile(r"^\s*PART\s+[IVXLCDM]+\s*$", re.IGNORECASE)
TOC_ITEM_RE = re.compile(r"^\s*ITEM\s+\d+[A-Z]?\.?\s*$", re.IGNORECASE)


def looks_like_toc_tabular(line: str) -> bool:
    """Return whether a line is dot-leader tabular content with a page token."""
    stripped = line.strip().strip("|+")
    if not stripped:
        return False
    return bool(
        RE_DOT_LEADER.search(stripped) and RE_PAGE_NUMBER_SUFFIX.search(stripped)
    )


def is_toc_row(line: str) -> bool:
    """Return whether line looks like a dot-leader TOC row."""
    stripped = line.strip().strip("|+")
    if not stripped:
        return False
    if RE_TOC_LEADER.search(stripped) and RE_PAGE_NUMBER_SUFFIX.search(stripped):
        return bool(
            RE_PART_REFERENCE.search(stripped) or RE_ITEM_REFERENCE.search(stripped)
        )
    return False


def looks_like_toc_row(line: str) -> bool:
    """Return whether line matches any TOC row form."""
    stripped = line.strip().strip("|+")
    if not stripped:
        return False
    if is_toc_row(stripped):
        return True
    return bool(
        RE_TOC_ITEM_ROW.match(stripped)
        and (RE_TOC_LEADER.search(stripped) or RE_PAGE_NUMBER_SUFFIX.search(stripped))
    )


def looks_like_toc_text(text: str) -> bool:
    """Recognize TOC context even when inline links split PART letters."""
    return bool("item" in text.casefold() and RE_TOC_PART_TEXT.search(text))


__all__ = [
    "PART_HEADING_RE",
    "RE_ITEM_REFERENCE",
    "RE_PART_REFERENCE",
    "RE_TOC_ITEM_ROW",
    "RE_TOC_LEADER",
    "RE_TOC_PART_TEXT",
    "TOC_ITEM_RE",
    "is_toc_row",
    "looks_like_toc_row",
    "looks_like_toc_tabular",
    "looks_like_toc_text",
]
