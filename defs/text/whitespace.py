"""Representation-neutral final text whitespace normalization."""

from __future__ import annotations

import re

from defs.regex import build_alternation
from defs.tables.protection import mask_tagged_tables, restore_tagged_tables
from defs.text.tokens import BULLET_MARKERS, GLYPH_BULLET_MARKERS

_ALL_BULLET_ALT = build_alternation(sorted(BULLET_MARKERS), auto_escape=True)
_GLYPH_BULLET_ALT = build_alternation(sorted(GLYPH_BULLET_MARKERS), auto_escape=True)

_RE_MULTIPLE_BLANKS = re.compile(r"\n{3,}")
_RE_TRAILING_WHITESPACE = re.compile(r"[ \t]+$", re.MULTILINE)

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


def split_concatenated_bullets(text: str) -> str:
    """Split inline concatenated bullet points and footnotes into separate lines.

    Punctuation-gated splitting ensures that inline column/field separators or
    hyphenated phrases are preserved, while list items concatenated onto a
    single line (e.g. following semicolons or periods) are split onto their own lines.
    """
    masked, table_spans = mask_tagged_tables(text)
    lines = masked.split("\n")
    new_lines = []
    for line in lines:
        if "__TAGGED_TABLE_" in line:
            new_lines.append(line)
            continue
        cleaned = _RE_SEMICOLON_BULLET_SPLIT.sub(r"\1\n", line)
        cleaned = _RE_PERIOD_GLYPH_BULLET_SPLIT.sub(r"\1\n", cleaned)
        cleaned = _RE_FOOTNOTE_BULLET_SPLIT.sub(r"\1\n", cleaned)
        new_lines.append(cleaned)
    result = "\n".join(new_lines)
    if table_spans:
        result = restore_tagged_tables(result, table_spans)
    return result


def normalize_final_text_whitespace(text: str) -> str:
    """Remove line-end padding, split concatenated bullets, and collapse excessive blank lines.

    Tagged tables are masked before whitespace cleanup so their internal
    spacing is preserved byte-for-byte.
    """
    masked, table_spans = mask_tagged_tables(text)
    cleaned = _RE_TRAILING_WHITESPACE.sub("", masked)
    cleaned = split_concatenated_bullets(cleaned)
    cleaned = _RE_MULTIPLE_BLANKS.sub("\n\n", cleaned)
    if table_spans:
        cleaned = restore_tagged_tables(cleaned, table_spans)
    return cleaned


__all__ = ["normalize_final_text_whitespace", "split_concatenated_bullets"]
