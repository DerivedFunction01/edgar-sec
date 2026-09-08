"""Representation-neutral final text whitespace normalization."""

from __future__ import annotations

import re

from defs.tables.protection import mask_tagged_tables, restore_tagged_tables

_RE_MULTIPLE_BLANKS = re.compile(r"\n{3,}")
_RE_TRAILING_WHITESPACE = re.compile(r"[ \t]+$", re.MULTILINE)


def normalize_final_text_whitespace(text: str) -> str:
    """Remove line-end padding and collapse excessive blank lines.

    Tagged tables are masked before whitespace cleanup so their internal
    spacing is preserved byte-for-byte.
    """
    masked, table_spans = mask_tagged_tables(text)
    cleaned = _RE_TRAILING_WHITESPACE.sub("", masked)
    cleaned = _RE_MULTIPLE_BLANKS.sub("\n\n", cleaned)
    if table_spans:
        cleaned = restore_tagged_tables(cleaned, table_spans)
    return cleaned


__all__ = ["normalize_final_text_whitespace"]
