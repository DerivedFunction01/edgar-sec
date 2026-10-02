"""HTML structural decomposition into plain text.

This is the projection step: block and inline markup become text, lists become
one item per line, headings become standalone lines, and everything else is
run together as prose. It is a *string* transform, not a DOM walk — the DOM
path exists in `tree.py`, and the reason this is string-based is that table
spans must survive the projection byte-for-byte, which is far simpler to
guarantee when the tagged table is masked out of the string first.

Order is load-bearing. Tables are masked before entity unescaping, so a table
containing `&amp;` is not silently rewritten; source line wraps are collapsed
before block tags are replaced, so a `<div>` split across source lines does not
gain spurious newlines.
"""

from __future__ import annotations

import html as html_lib
import re
from collections.abc import Callable
from typing import Self

from edgar_sec.engine.document.html.cleaner import clean_html_for_parsing
from edgar_sec.engine.document.html.tags import (
    CONTAINER_BLOCK_TAGS,
    INLINE_TAGS,
    PARAGRAPH_TAGS,
)
from edgar_sec.engine.tables.ascii_html.converter import (
    convert_html_tables_to_ascii_with_metadata,
)
from edgar_sec.engine.tables.ascii_html.model import TableGeometry
from edgar_sec.engine.tables.false_tables.unwrapper import (
    cleanup_false_tables_with_metadata,
)
from edgar_sec.engine.tables.hybrid.masker import (
    normalize_hybrid_pre_text,
    restore_hybrid_pre_text,
)
from edgar_sec.engine.tables.protection.tags import (
    SENTINEL_PREFIX,
    SENTINEL_SUFFIX,
    mask_tagged_tables,
    restore_tagged_tables,
)
from edgar_sec.foundation.regex.builder import build_alternation
from edgar_sec.foundation.text.normalize import sanitize_unicode_whitespace
from edgar_sec.foundation.text.tokens import is_list_or_bullet_marker

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

_RE_SENTINEL = re.compile(
    rf"({re.escape(SENTINEL_PREFIX)}\d+{re.escape(SENTINEL_SUFFIX)})"
)

_HEADING_TERMS_ALT = build_alternation(
    ["item", "part", "section", "rule", "paragraph"], auto_escape=True
)
_RE_HEADING_PREFIX = re.compile(rf"\b(?:{_HEADING_TERMS_ALT})\b$", re.IGNORECASE)


def _unify_dl_bullet(match: re.Match[str]) -> str:
    """Fuse a bullet-only ``<dt>`` into the ``<dd>`` that follows it.

    SEC cover pages mark list items with a bare glyph in the term slot; leaving
    that as its own line splits one item across two lines in plain text.
    """
    dt_content = match.group(1)
    dd_tag = match.group(2)
    clean_dt = _RE_TAG_STRIP.sub("", dt_content).strip()
    if is_list_or_bullet_marker(clean_dt):
        return f"{dd_tag}{clean_dt} "
    return match.group(0)


def _collapse_source_whitespace(match: re.Match[str]) -> str:
    """Collapse one raw source whitespace run outside a table span.

    A run separating two masked tables is a rendered separator, not a source
    line wrap: collapsing it to a space would fuse adjacent tables onto one
    line, so it becomes a real newline. A run followed by a bullet marker also
    becomes a newline, except directly after a heading word such as "Item",
    where the marker belongs to the heading line.
    """
    text = match.string
    start, end = match.span()
    token = text[start:end]
    if not token.isspace():
        return token
    before = text[max(0, start - 40) : start].rstrip()
    after = text[end : min(len(text), end + 50)].lstrip()
    if before.endswith(SENTINEL_SUFFIX) or after.startswith(SENTINEL_PREFIX):
        return "\n"
    first_token = after.split(maxsplit=1)[0] if after else ""
    if first_token and is_list_or_bullet_marker(first_token):
        if _RE_HEADING_PREFIX.search(before):
            return " "
        return "\n"
    return " "


def _clean_p_content(match: re.Match[str]) -> str:
    """Lift masked tables out of a ``<p>`` while keeping the prose above them.

    Filing generators sometimes wrap a table in a paragraph element. Emitting
    the table inside the paragraph's replacement gap would put table rows into
    the middle of prose, so the prose is unified into one ``<p>`` and the
    sentinels are emitted after it.
    """
    content = match.group(1)
    cleaned = _RE_DIV_TAG.sub(" ", content)

    parts = _RE_SENTINEL.split(cleaned)
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
        result_pieces.append(f"<p>{' '.join(prose_parts)}</p>")
    result_pieces.extend(sentinels)
    return "\n\n".join(result_pieces)


def decompose_html_structures(html: str) -> str:
    """Decompose block and inline HTML markup into normalized plain text.

    Paragraphs stay cohesive on one line, headings and block separators become
    clean vertical whitespace, redundant container ``<div>``s unroll, and
    masked ``<TABLE>`` blocks are restored byte-for-byte at the end.
    """
    if not html:
        return ""

    masked, spans = mask_tagged_tables(html)

    masked = html_lib.unescape(masked)
    masked = sanitize_unicode_whitespace(masked)
    masked = _RE_DECLARATIONS.sub("", masked)
    masked = _RE_COMMENTS.sub("", masked)

    masked = _RE_INLINE_DIV.sub(r"<span\1>", masked)

    masked = _RE_TRAILING_BR_DD.sub("", masked)
    masked = _RE_CONSECUTIVE_BR.sub("\n\n", masked)
    masked = _RE_SINGLE_BR.sub(" ", masked)

    for _ in range(3):
        masked = _RE_NESTED_DIV_OPEN.sub("<div>", masked)
        masked = _RE_NESTED_DIV_CLOSE.sub("</div>", masked)

    masked = _RE_P_CONTAINER.sub(_clean_p_content, masked)

    masked = _RE_RAW_SOURCE_WHITESPACE.sub(_collapse_source_whitespace, masked)

    masked = _RE_DL_ITEM.sub(_unify_dl_bullet, masked)
    masked = _RE_PARAGRAPH_TAGS.sub("\n\n", masked)
    masked = _RE_CONTAINER_TAGS.sub("\n", masked)

    masked = _RE_INLINE_TAGS.sub("", masked)
    masked = _RE_REMAINING_TAGS.sub("", masked)

    masked = _RE_HORIZONTAL_SPACES.sub(" ", masked)
    lines = [line.strip() for line in masked.split("\n")]
    masked = "\n".join(lines)
    masked = _RE_MULTIPLE_NEWLINES.sub("\n\n", masked)

    if spans:
        masked = restore_tagged_tables(masked, spans)
    return masked.strip()


class NormalizedHtmlText(str):
    """Normalized HTML text carrying the per-table geometry it was rendered from.

    A ``str`` subclass, so every comparison and string method behaves exactly as
    the plain text would, while :attr:`table_geometries` retains the row/cell
    layout that produced it. A caller cannot recover that mapping from the text
    alone, which is why it travels with the text rather than being recomputed.
    """

    __slots__ = ("_table_geometries",)

    def __new__(
        cls, text: str, table_geometries: tuple[TableGeometry, ...] = ()
    ) -> Self:
        instance = super().__new__(cls, text)
        instance._table_geometries = tuple(table_geometries)
        return instance

    @property
    def table_geometries(self) -> tuple[TableGeometry, ...]:
        """One geometry per table that produced rendered output."""
        return self._table_geometries

    def __repr__(self) -> str:
        return (
            f"NormalizedHtmlText({super().__repr__()!r}, "
            f"table_geometries={self._table_geometries!r})"
        )


def normalize_html_document(
    html: str,
    *,
    cleanup_tables: Callable[[str], str] | None = None,
) -> NormalizedHtmlText:
    """Render an HTML document into normalized text without tree text extraction.

    Tables are rendered while the surrounding markup stays serialized, so
    :func:`decompose_html_structures` can still preserve paragraph cohesion —
    projecting the DOM to text first would flatten exactly the structure the
    decomposition pass exists to keep.

    Rendered tables are then protected by the projection pass through the
    byte-exact masking contract in `edgar_sec.engine.tables.protection.tags`.

    ``cleanup_tables`` is injectable for focused tests and policy experiments.
    Omitting it selects the shared false-table cleanup, which also retains the
    geometry of every table it kept; supplying it means the caller owns the
    returned geometry and the default is not applied.

    Returns a :class:`NormalizedHtmlText`, which compares equal to the
    normalized string while exposing :attr:`table_geometries`.
    """
    if not html:
        return NormalizedHtmlText("", ())

    metadata_cleanup = cleanup_tables is None

    cleaned = clean_html_for_parsing(html)
    hybrid = normalize_hybrid_pre_text(cleaned)
    rendered, geometries = convert_html_tables_to_ascii_with_metadata(
        hybrid.text,
        convert_to_text=False,
        early_unwrap_false_tables=metadata_cleanup,
    )
    if metadata_cleanup:
        rendered, geometries = cleanup_false_tables_with_metadata(rendered, geometries)
    else:
        rendered = cleanup_tables(rendered)
    normalized = decompose_html_structures(rendered)
    if hybrid.protected:
        normalized = restore_hybrid_pre_text(normalized, hybrid.protected)
    return NormalizedHtmlText(normalized, geometries)


__all__ = [
    "NormalizedHtmlText",
    "decompose_html_structures",
    "normalize_html_document",
]
