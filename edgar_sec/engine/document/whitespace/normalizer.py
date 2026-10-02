"""Final whitespace normalization for normalized document text.

Cleans trailing line-end padding, splits list items that the source concatenated
onto one line, and collapses excessive blank runs — problems that become visible
after cover stages have run. Runs prior to body reflow on ASCII documents.

Tagged tables are masked first, so their internal spacing survives byte-for-byte.
"""

from __future__ import annotations

import re

from edgar_sec.engine.tables.protection.tags import (
    SENTINEL_PREFIX,
    mask_tagged_tables,
    restore_tagged_tables,
)
from edgar_sec.foundation.regex.builder import build_alternation
from edgar_sec.foundation.text.tokens import BULLET_MARKERS, GLYPH_BULLET_MARKERS

_ALL_BULLET_ALT = build_alternation(sorted(BULLET_MARKERS), auto_escape=True)
_GLYPH_BULLET_ALT = build_alternation(sorted(GLYPH_BULLET_MARKERS), auto_escape=True)

_RE_MULTIPLE_BLANKS = re.compile(r"\n{3,}")

# Concatenated-item splitting. Each rule is gated on punctuation so that an
# inline column separator or a hyphenated phrase is not mistaken for a list
# boundary, and each requires a following alphanumeric so a trailing colon
# at end of line is left alone.
_RE_SEMICOLON_BULLET_SPLIT = re.compile(
    rf"([;:](?:[ \t]+(?:and|or))?)[ \t]+(?=(?:{_ALL_BULLET_ALT})[ \t]+[A-Za-z0-9\(\$])",
    re.IGNORECASE,
)
_RE_PERIOD_GLYPH_BULLET_SPLIT = re.compile(
    rf"([.\)](?:[ \t]+(?:and|or))?)[ \t]+(?=(?:{_GLYPH_BULLET_ALT})[ \t]+[A-Za-z0-9\(\$])",
    re.IGNORECASE,
)
_RE_FOOTNOTE_BULLET_SPLIT = re.compile(r"(\.)[ \t]+(?=\*{1,3}[ \t]+[A-Za-z0-9\(\$])")


def _split_bullets_on_masked(masked: str) -> str:
    lines = masked.split("\n")
    new_lines = []
    for line in lines:
        stripped = line.rstrip(" \t")
        if SENTINEL_PREFIX in stripped:
            new_lines.append(stripped)
            continue
        cleaned = _RE_SEMICOLON_BULLET_SPLIT.sub(r"\1\n", stripped)
        cleaned = _RE_PERIOD_GLYPH_BULLET_SPLIT.sub(r"\1\n", cleaned)
        cleaned = _RE_FOOTNOTE_BULLET_SPLIT.sub(r"\1\n", cleaned)
        new_lines.append(cleaned)
    return "\n".join(new_lines)


def split_concatenated_bullets(text: str) -> str:
    """Split list items and footnotes the source ran together onto one line."""
    masked, table_spans = mask_tagged_tables(text)
    result = _split_bullets_on_masked(masked)
    if table_spans:
        result = restore_tagged_tables(result, table_spans)
    return result


def normalize_final_text_whitespace(text: str) -> str:
    """Remove line-end padding, split concatenated items, collapse blank runs."""
    masked, table_spans = mask_tagged_tables(text)
    cleaned = _split_bullets_on_masked(masked)
    cleaned = _RE_MULTIPLE_BLANKS.sub("\n\n", cleaned)
    if table_spans:
        cleaned = restore_tagged_tables(cleaned, table_spans)
    return cleaned


__all__ = ["normalize_final_text_whitespace", "split_concatenated_bullets"]
