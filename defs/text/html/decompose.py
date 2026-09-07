"""HTML structural decomposition into standard text, lists, headings, and breaks."""

from __future__ import annotations

import html as html_lib
import re

from defs.regex import build_alternation
from defs.text.unicode import sanitize_unicode_whitespace

from .tags import CONTAINER_BLOCK_TAGS, INLINE_TAGS, PARAGRAPH_TAGS

_PARAGRAPH_TAGS_ALT = build_alternation(sorted(PARAGRAPH_TAGS), auto_escape=True)
_CONTAINER_TAGS_ALT = build_alternation(sorted(CONTAINER_BLOCK_TAGS), auto_escape=True)
_INLINE_TAGS_ALT = build_alternation(sorted(INLINE_TAGS), auto_escape=True)

_RE_PARAGRAPH_TAGS = re.compile(rf"</?(?:{_PARAGRAPH_TAGS_ALT})\b[^>]*>", re.IGNORECASE)
_RE_CONTAINER_TAGS = re.compile(rf"</?(?:{_CONTAINER_TAGS_ALT})\b[^>]*>", re.IGNORECASE)
_RE_INLINE_TAGS = re.compile(rf"</?(?:{_INLINE_TAGS_ALT})\b[^>]*>", re.IGNORECASE)
_RE_REMAINING_TAGS = re.compile(r"<[^>]+>")
_RE_HORIZONTAL_SPACES = re.compile(r"[^\S\n]+")
_RE_MULTIPLE_NEWLINES = re.compile(r"\n{3,}")

_RE_CONSECUTIVE_BR = re.compile(r"(?:<br\s*/?>\s*){2,}", re.IGNORECASE)
_RE_SINGLE_BR = re.compile(r"<br\s*/?>", re.IGNORECASE)
_RE_INLINE_DIV = re.compile(
    r"<div\b([^>]*style=[\x22\x27][^\x22\x27]*display\s*:\s*inline[^\x22\x27]*[\x22\x27][^>]*)>",
    re.IGNORECASE,
)
_RE_NESTED_DIV_OPEN = re.compile(r"<div\b[^>]*>\s*<div\b[^>]*>", re.IGNORECASE)
_RE_NESTED_DIV_CLOSE = re.compile(r"</div>\s*</div>", re.IGNORECASE)
_RE_P_CONTAINER = re.compile(r"<p\b[^>]*>(.*?)</p>", re.DOTALL | re.IGNORECASE)
_RE_DIV_TAG = re.compile(r"</?div\b[^>]*>", re.IGNORECASE)
_RE_RAW_SOURCE_WHITESPACE = re.compile(r"[\r\n\t]+")


def _clean_p_content(match: re.Match[str]) -> str:
    """Strip layout containers inside paragraph elements so text flows as single lines."""
    content = match.group(1)
    cleaned = _RE_DIV_TAG.sub(" ", content)
    return f"<p>{cleaned}</p>"


def decompose_html_structures(html: str) -> str:
    """Decompose block and inline HTML tags into normalized plain text.

    Preserves paragraph cohesion on single lines, converts headings and block
    separators into clean vertical whitespace, unrolls redundant container divs,
    and protects rendered <TABLE>...</TABLE> blocks.
    """
    if not html:
        return ""
    from defs.tables.protection import mask_tagged_tables, restore_tagged_tables

    # 1. Mask rendered tables and preformatted blocks
    masked, spans = mask_tagged_tables(html)

    # 2. Unescape entities and sanitize Unicode whitespace
    masked = html_lib.unescape(masked)
    masked = sanitize_unicode_whitespace(masked)

    # 3. Convert display:inline divs to spans
    masked = _RE_INLINE_DIV.sub(r"<span\1>", masked)

    # 4. Handle line breaks (consecutive <br> to \n\n, single <br> to space)
    masked = _RE_CONSECUTIVE_BR.sub("\n\n", masked)
    masked = _RE_SINGLE_BR.sub(" ", masked)

    # 5. Unnest redundant container divs
    for _ in range(3):
        masked = _RE_NESTED_DIV_OPEN.sub("<div>", masked)
        masked = _RE_NESTED_DIV_CLOSE.sub("</div>", masked)

    # 6. Clean paragraph-internal container divs
    masked = _RE_P_CONTAINER.sub(_clean_p_content, masked)

    # 7. Collapse raw source-code line wraps outside tables
    masked = _RE_RAW_SOURCE_WHITESPACE.sub(" ", masked)

    # 8. Delimit semantic block boundaries
    masked = _RE_PARAGRAPH_TAGS.sub("\n\n", masked)
    masked = _RE_CONTAINER_TAGS.sub("\n", masked)

    # 9. Strip inline tags and remaining markup
    masked = _RE_INLINE_TAGS.sub("", masked)
    masked = _RE_REMAINING_TAGS.sub("", masked)

    # 10. Normalize whitespace and trailing line breaks
    masked = _RE_HORIZONTAL_SPACES.sub(" ", masked)
    lines = [line.strip() for line in masked.split("\n")]
    masked = "\n".join(lines)
    masked = _RE_MULTIPLE_NEWLINES.sub("\n\n", masked)

    # 11. Restore protected tables
    if spans:
        masked = restore_tagged_tables(masked, spans)
    return masked.strip()


__all__ = ["decompose_html_structures"]
