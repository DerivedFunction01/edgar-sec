"""Representation-neutral final text whitespace normalization."""

from __future__ import annotations

import re

from defs.regex import build_alternation

_SENTINEL_PREFIX = "__SEC_TBL_"
from defs.text.syntax.tokens import BULLET_MARKERS, GLYPH_BULLET_MARKERS

_ALL_BULLET_ALT = build_alternation(sorted(BULLET_MARKERS), auto_escape=True)
_GLYPH_BULLET_ALT = build_alternation(sorted(GLYPH_BULLET_MARKERS), auto_escape=True)

_RE_MULTIPLE_BLANKS = re.compile(r"\n{3,}")

# Concatenated bullet splitting patterns
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
        if _SENTINEL_PREFIX in stripped:
            new_lines.append(stripped)
            continue
        cleaned = _RE_SEMICOLON_BULLET_SPLIT.sub(r"\1\n", stripped)
        cleaned = _RE_PERIOD_GLYPH_BULLET_SPLIT.sub(r"\1\n", cleaned)
        cleaned = _RE_FOOTNOTE_BULLET_SPLIT.sub(r"\1\n", cleaned)
        new_lines.append(cleaned)
    return "\n".join(new_lines)


def split_concatenated_bullets(text: str) -> str:
    """Split inline concatenated bullet points and footnotes into separate lines.

    Punctuation-gated splitting ensures that inline column/field separators or
    hyphenated phrases are preserved, while list items concatenated onto a
    single line (e.g. following semicolons or periods) are split onto their own lines.
    """
    from defs.tables.protection import mask_tagged_tables, restore_tagged_tables

    masked, table_spans = mask_tagged_tables(text)
    result = _split_bullets_on_masked(masked)
    if table_spans:
        result = restore_tagged_tables(result, table_spans)
    return result


def normalize_final_text_whitespace(text: str) -> str:
    """Remove line-end padding, split concatenated bullets, and collapse excessive blank lines.

    Tagged tables are masked before whitespace cleanup so their internal
    spacing is preserved byte-for-byte.
    """
    from defs.tables.protection import mask_tagged_tables, restore_tagged_tables

    masked, table_spans = mask_tagged_tables(text)
    cleaned = _split_bullets_on_masked(masked)
    cleaned = _RE_MULTIPLE_BLANKS.sub("\n\n", cleaned)
    if table_spans:
        cleaned = restore_tagged_tables(cleaned, table_spans)
    return cleaned


__all__ = ["normalize_final_text_whitespace", "split_concatenated_bullets"]
