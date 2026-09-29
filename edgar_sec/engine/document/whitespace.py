"""Representation-neutral final-text whitespace normalization.

Whitespace cleanup is the last stage of the normalization pipeline, but it is
not representation-neutral in effect: tagged ``<TABLE>`` blocks must survive
byte-for-byte. Every pass here therefore masks table spans behind sentinels,
rewrites only the prose between them, and restores the originals afterwards.
"""

from __future__ import annotations

import re

from edgar_sec.engine.tables.protection import (
    SENTINEL_PREFIX,
    mask_tagged_tables,
    restore_tagged_tables,
)
from edgar_sec.foundation.regex.builder import build_alternation
from edgar_sec.foundation.text.tokens import BULLET_MARKERS, GLYPH_BULLET_MARKERS

_ALL_BULLET_ALT = build_alternation(sorted(BULLET_MARKERS), auto_escape=True)
_GLYPH_BULLET_ALT = build_alternation(sorted(GLYPH_BULLET_MARKERS), auto_escape=True)

_RE_MULTIPLE_BLANKS = re.compile(r"\n{3,}")
_RE_LINE_END_PADDING = re.compile(r"[ \t]+$", re.MULTILINE)

# Punctuation-gated bullet splitting: a bullet is only split onto its own line
# when the preceding punctuation already terminates a clause, so inline column
# separators and hyphenated phrases are left intact.
_RE_SEMICOLON_BULLET_SPLIT = re.compile(
    rf"([;:](?:[ \t]+(?:and|or))?)[ \t]+(?=(?:{_ALL_BULLET_ALT})[ \t]+[A-Za-z0-9(\$])",
    re.IGNORECASE,
)
_RE_PERIOD_GLYPH_BULLET_SPLIT = re.compile(
    rf"([.\)](?:[ \t]+(?:and|or))?)[ \t]+(?=(?:{_GLYPH_BULLET_ALT})[ \t]+[A-Za-z0-9(\$])",
    re.IGNORECASE,
)
_RE_FOOTNOTE_BULLET_SPLIT = re.compile(r"(\.)[ \t]+(?=\*{1,3}[ \t]+[A-Za-z0-9(\$])")


def _split_bullets_on_masked(masked: str) -> str:
    lines = masked.split("\n")
    cleaned_lines: list[str] = []
    for line in lines:
        stripped = _RE_LINE_END_PADDING.sub("", line)
        if SENTINEL_PREFIX in stripped:
            cleaned_lines.append(stripped)
            continue
        cleaned = _RE_SEMICOLON_BULLET_SPLIT.sub(r"\1\n", stripped)
        cleaned = _RE_PERIOD_GLYPH_BULLET_SPLIT.sub(r"\1\n", cleaned)
        cleaned = _RE_FOOTNOTE_BULLET_SPLIT.sub(r"\1\n", cleaned)
        cleaned_lines.append(cleaned)
    return "\n".join(cleaned_lines)


def split_concatenated_bullets(text: str) -> str:
    """Split inline concatenated bullet points and footnotes onto separate lines."""
    if not text:
        return ""
    masked, table_spans = mask_tagged_tables(text)
    result = _split_bullets_on_masked(masked)
    if table_spans:
        result = restore_tagged_tables(result, table_spans)
    return result


def normalize_final_text_whitespace(text: str) -> str:
    """Remove line-end padding, split concatenated bullets, collapse blank runs.

    Tagged tables are masked before cleanup so their internal spacing is
    preserved byte-for-byte.
    """
    if not text:
        return ""
    masked, table_spans = mask_tagged_tables(text)
    cleaned = _split_bullets_on_masked(masked)
    cleaned = _RE_MULTIPLE_BLANKS.sub("\n\n", cleaned)
    if table_spans:
        cleaned = restore_tagged_tables(cleaned, table_spans)
    return cleaned


def count_lines(text: str) -> int:
    """Count newline-delimited lines without materializing a line list.

    Equivalent to ``len(text.splitlines())`` for text whose only line separator
    is ``\\n`` without a trailing newline. Other Unicode line separators are not
    counted; callers use this for diagnostics only.
    """
    if not text:
        return 0
    return text.count("\n") + (0 if text.endswith("\n") else 1)


__all__ = [
    "count_lines",
    "normalize_final_text_whitespace",
    "split_concatenated_bullets",
]
