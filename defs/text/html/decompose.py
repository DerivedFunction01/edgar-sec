"""HTML structural decomposition into standard text, lists, headings, and breaks."""

from __future__ import annotations

import html as html_lib
import re

from defs.regex import build_alternation
from defs.text.tokens import is_list_or_bullet_marker
from defs.text.unicode import sanitize_unicode_whitespace

from .tags import CONTAINER_BLOCK_TAGS, INLINE_TAGS, PARAGRAPH_TAGS

_PARAGRAPH_TAGS_ALT = build_alternation(sorted(PARAGRAPH_TAGS), auto_escape=True)
_CONTAINER_TAGS_ALT = build_alternation(sorted(CONTAINER_BLOCK_TAGS), auto_escape=True)
_INLINE_TAGS_ALT = build_alternation(sorted(INLINE_TAGS), auto_escape=True)

_RE_PARAGRAPH_TAGS = re.compile(rf"</?(?:{_PARAGRAPH_TAGS_ALT})\b[^>]*>", re.IGNORECASE)
_RE_CONTAINER_TAGS = re.compile(rf"</?(?:{_CONTAINER_TAGS_ALT})\b[^>]*>", re.IGNORECASE)
_RE_INLINE_TAGS = re.compile(rf"</?(?:{_INLINE_TAGS_ALT})\b[^>]*>", re.IGNORECASE)
_RE_REMAINING_TAGS = re.compile(r"</?[a-zA-Z][^>]*>")
_RE_COMMENTS = re.compile(r"<!--.*?-->", re.DOTALL)
_RE_DECLARATIONS = re.compile(r"<!DOCTYPE[^>]*>|<\?[^>]*\?>", re.IGNORECASE | re.DOTALL)
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

_RE_DL_ITEM = re.compile(
    r"<dt\b[^>]*>(.*?)</dt>\s*(<dd\b[^>]*>)",
    re.IGNORECASE | re.DOTALL,
)
_RE_TRAILING_BR_DD = re.compile(r"(?:<br\s*/?>\s*)+(?=</dd>)", re.IGNORECASE)
_RE_TAG_STRIP = re.compile(r"<[^>]+>")


def _unify_dl_bullet(match: re.Match[str]) -> str:
    """Unify definition list markers with their description content.

    When a <dt> contains only a bullet or list marker, fuse it directly into
    the succeeding <dd> block so list items render with their marker inline.
    """
    dt_content = match.group(1)
    dd_tag = match.group(2)
    clean_dt = _RE_TAG_STRIP.sub("", dt_content).strip()
    if is_list_or_bullet_marker(clean_dt):
        return f"{dd_tag}{clean_dt} "
    return match.group(0)


def _collapse_source_whitespace_factory(sentinel_prefix: str, sentinel_suffix: str):
    """Build a whitespace-run collapser that keeps table-sentinel separators.

    A whitespace run that separates two masked-table sentinels (or touches a
    sentinel boundary) is a rendered table separator, not a source-code line
    wrap: collapsing it to a space would fuse adjacent tables onto one line.
    """

    def _collapse(match: re.Match[str]) -> str:
        text = match.string
        start, end = match.span()
        token = text[start:end]
        if not token.isspace():
            return token
        before = text[:start].rstrip()
        after = text[end:].lstrip()
        if before.endswith(sentinel_suffix) or after.startswith(sentinel_prefix):
            return "\n"
        first_token = after.split(maxsplit=1)[0] if after else ""
        if first_token and is_list_or_bullet_marker(first_token):
            return "\n"
        return " "

    return _collapse


def _clean_p_content(match: re.Match[str]) -> str:
    """Strip layout containers inside paragraph elements so text flows as single lines.

    When a table was embedded inside a <p> container in HTML, lift the table
    outside the <p> while preserving the continuous paragraph prose above it.
    """
    from defs.tables.protection import SENTINEL_PREFIX, SENTINEL_SUFFIX

    content = match.group(1)
    cleaned = _RE_DIV_TAG.sub(" ", content)

    sentinel_pattern = re.compile(
        rf"({re.escape(SENTINEL_PREFIX)}\d+{re.escape(SENTINEL_SUFFIX)})"
    )
    parts = sentinel_pattern.split(cleaned)
    if len(parts) == 1:
        return f"<p>{cleaned}</p>"

    prose_parts = []
    sentinels = []
    for i, part in enumerate(parts):
        if i % 2 == 0:
            if part.strip():
                prose_parts.append(part.strip())
        else:
            sentinels.append(part)

    result_pieces = []
    if prose_parts:
        unified_prose = " ".join(prose_parts)
        result_pieces.append(f"<p>{unified_prose}</p>")
    result_pieces.extend(sentinels)
    return "\n\n".join(result_pieces)


def decompose_html_structures(html: str) -> str:
    """Decompose block and inline HTML tags into normalized plain text.

    Preserves paragraph cohesion on single lines, converts headings and block
    separators into clean vertical whitespace, unrolls redundant container divs,
    and protects rendered <TABLE>...</TABLE> blocks.
    """
    if not html:
        return ""
    from defs.tables.protection import (
        SENTINEL_PREFIX,
        SENTINEL_SUFFIX,
        mask_tagged_tables,
        restore_tagged_tables,
    )

    # 1. Mask rendered tables and preformatted blocks
    masked, spans = mask_tagged_tables(html)

    # 2. Unescape entities and sanitize Unicode whitespace
    masked = html_lib.unescape(masked)
    masked = sanitize_unicode_whitespace(masked)
    masked = _RE_DECLARATIONS.sub("", masked)
    masked = _RE_COMMENTS.sub("", masked)

    # 3. Convert display:inline divs to spans
    masked = _RE_INLINE_DIV.sub(r"<span\1>", masked)

    # 4. Strip redundant trailing breaks in description lists, then handle line breaks
    masked = _RE_TRAILING_BR_DD.sub("", masked)
    masked = _RE_CONSECUTIVE_BR.sub("\n\n", masked)
    masked = _RE_SINGLE_BR.sub(" ", masked)

    # 5. Unnest redundant container divs
    for _ in range(3):
        masked = _RE_NESTED_DIV_OPEN.sub("<div>", masked)
        masked = _RE_NESTED_DIV_CLOSE.sub("</div>", masked)

    # 6. Clean paragraph-internal container divs
    masked = _RE_P_CONTAINER.sub(_clean_p_content, masked)

    # 7. Collapse raw source-code line wraps outside tables, keeping the
    # separator between adjacent masked tables as a real line break
    masked = _RE_RAW_SOURCE_WHITESPACE.sub(
        _collapse_source_whitespace_factory(SENTINEL_PREFIX, SENTINEL_SUFFIX), masked
    )

    # 8. Unify definition-list bullets and delimit semantic block boundaries
    masked = _RE_DL_ITEM.sub(_unify_dl_bullet, masked)
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
