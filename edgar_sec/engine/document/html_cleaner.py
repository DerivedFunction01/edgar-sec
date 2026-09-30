"""High-throughput Stage-1 HTML pre-cleaning and structural decomposition.

Removes transport and presentation noise, strips benign font declarations,
and decomposes HTML tags into normalized text while protecting rendered tables.
"""

from __future__ import annotations

import html as html_lib
import re

from edgar_sec.domain.forms.checkmarks import (
    CANONICAL_CHECKED,
    CANONICAL_UNCHECKED,
    font_bullet_glyph_state,
    font_glyph_state,
)
from edgar_sec.engine.tables.protection import (
    SENTINEL_PREFIX,
    SENTINEL_SUFFIX,
    mask_tagged_tables,
    restore_tagged_tables,
)
from edgar_sec.foundation.regex.builder import build_alternation
from edgar_sec.foundation.text.normalize import sanitize_unicode_whitespace
from edgar_sec.foundation.text.tokens import is_list_or_bullet_marker

# ---------------------------------------------------------------------------
# Canonical HTML tag classifications
# ---------------------------------------------------------------------------
PARAGRAPH_TAGS: frozenset[str] = frozenset(
    {"p", "blockquote", "h1", "h2", "h3", "h4", "h5", "h6"}
)

CONTAINER_BLOCK_TAGS: frozenset[str] = frozenset(
    {
        "address",
        "article",
        "aside",
        "dd",
        "div",
        "dl",
        "dt",
        "fieldset",
        "figcaption",
        "figure",
        "footer",
        "form",
        "header",
        "hr",
        "li",
        "main",
        "nav",
        "noscript",
        "ol",
        "section",
        "ul",
    }
)

TABLE_AND_PRE_TAGS: frozenset[str] = frozenset(
    {"table", "tbody", "thead", "tfoot", "tr", "td", "th", "pre"}
)

BLOCK_TAGS: frozenset[str] = PARAGRAPH_TAGS | CONTAINER_BLOCK_TAGS | TABLE_AND_PRE_TAGS

INLINE_TAGS: frozenset[str] = frozenset(
    {
        "a",
        "abbr",
        "b",
        "big",
        "center",
        "cite",
        "code",
        "del",
        "em",
        "font",
        "i",
        "ins",
        "q",
        "s",
        "small",
        "span",
        "strike",
        "strong",
        "sub",
        "sup",
        "u",
    }
)

# ---------------------------------------------------------------------------
# Stage-1 HTML Pre-Cleaner: Regex patterns
# ---------------------------------------------------------------------------
_RE_IX_HEADER_BLOCK = re.compile(r"(?is)<ix:header\b.*?</ix:header>")
_RE_IX_HIDDEN_BLOCK = re.compile(r"(?is)<ix:hidden\b.*?</ix:hidden>")
_IXBRL_PREFIXES = build_alternation(["ix", "xbrl", "xbrli", "dei", "us-gaap"])
_RE_IXBRL_TAG = re.compile(rf"(?i)</?(?:{_IXBRL_PREFIXES}):[a-z][a-z0-9_.-]*[^>]*>")

_PRESERVED_FAMILIES = ("wingdings", "webdings", "symbol")
_PRESERVED_FAMILIES_ALT = build_alternation(_PRESERVED_FAMILIES, auto_escape=True)
_RE_HAS_PRESERVED_FAMILY = re.compile(rf"(?i)\b(?:{_PRESERVED_FAMILIES_ALT})\b")

_BOX_SPACING_ALT = build_alternation(["margin", "padding"], auto_escape=True)
_TYPOGRAPHY_ALT = build_alternation(
    [
        "line-height",
        "letter-spacing",
        "word-spacing",
        "text-indent",
        "text-decoration",
    ],
    auto_escape=True,
)
_MISC_STYLE_ALT = build_alternation(
    [
        "cursor",
        "z-index",
        "overflow",
        "clear",
        "float",
        "box-sizing",
        "outline",
        "opacity",
    ],
    auto_escape=True,
)
_SIDE_SUFFIX_ALT = build_alternation(
    ["top", "bottom", "left", "right"], auto_escape=True
)

_RE_BENIGN_STYLE_DECL = re.compile(
    r"(?i)(?<![a-z-])(?:"
    rf"font-family\s*:\s*(?![^;\"'\n>]*(?:{_PRESERVED_FAMILIES_ALT}))[^;\"'\n>]*"
    r"|font-size\s*:[^;\"'\n>]*"
    r"|(?:background-)?color\s*:[^;\"'\n>]*"
    rf"|(?:{_BOX_SPACING_ALT})(?:-(?:{_SIDE_SUFFIX_ALT}))?\s*:[^;\"'\n>]*"
    rf"|(?:{_TYPOGRAPHY_ALT})\s*:[^;\"'\n>]*"
    rf"|(?:{_MISC_STYLE_ALT})\s*:[^;\"'\n>]*"
    r");?"
)

_RE_REDUNDANT_SEPARATORS = re.compile(r";\s*;")
_RE_EMPTY_STYLE_ATTR = re.compile(r'(?i)(?<=[\s"])style\s*=\s*"\s*"')

_RE_TAG_OR_TEXT = re.compile(r"(?is)<!--.*?-->|<[^>]*>|[^<]+")
_RE_STYLE_FONT_FAMILY = re.compile(
    r"(?i)\bfont-family\s*:\s*([^;\"]+)|(?<=style=[\"'])\s*([a-z0-9\s,'\"_-]+?)(?:;|\"|'|$)"
)
_RE_FACE_ATTR = re.compile(r"(?i)\bface\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|([^\s>]+))")
_RE_GLYPH = re.compile(r"[\u00a8\u00a3\u00fe\u00fdrRnNuUoOxX]")
_VOID_TAGS = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }
)

_RE_FONT_TAG = re.compile(r"(?i)<font\b([^>]*)>")
_RE_FONT_ATTRS = re.compile(
    r"""(?i)\s+(?:face=(?:"([^"]*)"|'([^']*)'|([^\s>]+))|(?:size|color)=(?:"[^"]*"|'[^']*'|[^\s>]+))"""
)

_NOISE_ATTRS_ALT = build_alternation(
    ["tabindex", "target", "shape", "coords"], auto_escape=True
)
_RE_NOISE_ATTRS = re.compile(
    rf"(?i)\s+(?:{_NOISE_ATTRS_ALT})=(?:[\"'][^>\"']*[\"']|[^>\s\"']+)"
)

_METADATA_PREFIX_ALT = build_alternation(["mso", "data"], auto_escape=True)
_METADATA_LANG_ALT = build_alternation(["xml:lang", "lang"], auto_escape=True)
_RE_METADATA_ATTR = re.compile(
    rf"""(?i)\s+(?:(?:{_METADATA_PREFIX_ALT})-[a-z0-9_.-]+|(?:{_METADATA_LANG_ALT}))\s*=\s*(?:"[^"]*"|'[^']*')"""
)

_TOC_NAV_PHRASES = build_alternation(
    [
        r"table\s+of\s+contents",
        r"return\s+to\s+table\s+of\s+contents",
        r"index\s+to\s+(?:financial\s+statements|exhibits)",
        r"back\s+to\s+top",
    ],
    auto_escape=False,
)
_RE_TOC_NAV_LINK = re.compile(
    rf"""(?is)<a\b[^>]*\bhref\s*=\s*["']#[^"']*["'][^>]*>\s*(?:<[^>]+>\s*)*(?:{_TOC_NAV_PHRASES})\s*(?:</[^>]+>\s*)*</a>"""
)


def _replace_font_glyphs(text: str, font_family: str) -> str:
    stripped = text.strip()
    is_standalone = len(stripped) <= 3

    def replace(match: re.Match[str]) -> str:
        glyph = match.group(0)
        if (
            glyph in {"r", "R", "o", "O", "x", "X", "s", "S", "n", "N", "u", "U"}
            and not is_standalone
        ):
            return glyph
        start, end = match.start(), match.end()
        if (
            start > 0
            and end < len(text)
            and text[start - 1] in "[(/"
            and text[end] in "])/"
        ):
            return glyph
        if start >= 2 and end <= len(text) - 2:
            surrounding = text[start - 2 : end + 2]
            if (
                surrounding[0] in "[("
                and surrounding[-1] in "])"
                and surrounding[1] in "xXoOsSrRnNuU"
            ):
                return glyph
        bullet = font_bullet_glyph_state(font_family, glyph)
        if bullet is not None:
            return bullet
        state = font_glyph_state(font_family, glyph)
        if state == "checked":
            return CANONICAL_CHECKED
        if state == "unchecked":
            return CANONICAL_UNCHECKED
        return glyph

    return _RE_GLYPH.sub(replace, text)


def strip_ixbrl_inline_tags(html: str) -> str:
    """Unwrap inline XBRL tags while keeping their inner text content."""
    if ":" not in html:
        return html
    if "ix:header" in html or "IX:HEADER" in html:
        html = _RE_IX_HEADER_BLOCK.sub(" ", html)
    if "ix:hidden" in html or "IX:HIDDEN" in html:
        html = _RE_IX_HIDDEN_BLOCK.sub(" ", html)
    return _RE_IXBRL_TAG.sub("", html)


def normalize_font_qualified_glyphs(html: str) -> str:
    """Map only glyphs in text nodes with an explicit symbolic font."""
    if not html or not _RE_HAS_PRESERVED_FAMILY.search(html):
        return html

    output: list[str] = []
    font_stack: list[str | None] = []
    current_font: str | None = None
    opaque_depth = 0
    for match in _RE_TAG_OR_TEXT.finditer(html):
        token = match.group(0)
        if token[0] != "<":
            if opaque_depth or current_font is None:
                output.append(token)
            else:
                output.append(_replace_font_glyphs(token, current_font))
            continue

        if token.startswith("<!--"):
            output.append(token)
            continue

        is_closing = len(token) > 1 and token[1] == "/"
        output.append(token)

        if is_closing:
            tag_name = (
                token[2:].split()[0].rstrip(">").lower() if len(token) > 2 else ""
            )
            if tag_name in ("script", "style") and opaque_depth:
                opaque_depth -= 1
            if font_stack:
                current_font = font_stack.pop()
            continue

        tag_part = token[1:].split(None, 1)[0].rstrip("/>")
        tag_name = tag_part.lower()
        if tag_name in ("script", "style"):
            opaque_depth += 1
        if tag_name in _VOID_TAGS or token.endswith("/>"):
            continue

        font_stack.append(current_font)
        tok_lower = token.lower()
        if "font-family" in tok_lower:
            style_match = _RE_STYLE_FONT_FAMILY.search(token)
            if style_match:
                current_font = (
                    style_match.group(1) or style_match.group(2) or ""
                ).strip()
                continue
        if "face=" in tok_lower or "face =" in tok_lower:
            face_match = _RE_FACE_ATTR.search(token)
            if face_match:
                current_font = next(
                    (value for value in face_match.groups() if value is not None), ""
                ).strip()

    return "".join(output)


def strip_benign_font_styles(html: str) -> str:
    """Strip redundant standard font and layout declarations from style attributes."""
    if "style=" not in html and "style =" not in html:
        return html
    html = _RE_BENIGN_STYLE_DECL.sub("", html)
    html = _RE_REDUNDANT_SEPARATORS.sub(";", html)
    return _RE_EMPTY_STYLE_ATTR.sub("", html)


def strip_office_metadata_attributes(html: str) -> str:
    """Strip mso-*, data-*, xml:lang, and lang attributes."""
    if (
        "mso-" not in html
        and "data-" not in html
        and "lang=" not in html
        and "LANG=" not in html
    ):
        return html
    return _RE_METADATA_ATTR.sub("", html)


def strip_font_tag_and_noise_attributes(html: str) -> str:
    """Strip legacy non-symbolic font face/size/color and noise attributes."""
    if "<font" in html or "<FONT" in html:

        def _clean_tag(match: re.Match[str]) -> str:
            attrs = match.group(1)

            def _clean_attr(m: re.Match[str]) -> str:
                face_val = m.group(1) or m.group(2) or m.group(3)
                if face_val and _RE_HAS_PRESERVED_FAMILY.search(face_val):
                    return m.group(0)
                return ""

            new_attrs = _RE_FONT_ATTRS.sub(_clean_attr, attrs)
            return f"<font{new_attrs}>"

        html = _RE_FONT_TAG.sub(_clean_tag, html)
    if (
        "tabindex=" in html
        or "target=" in html
        or "shape=" in html
        or "coords=" in html
    ):
        html = _RE_NOISE_ATTRS.sub("", html)
    return html


def strip_toc_navigation_links(html: str) -> str:
    """Strip web-only intra-document TOC jump-links."""
    if "href=" not in html and "href =" not in html and "HREF=" not in html:
        return html
    return _RE_TOC_NAV_LINK.sub("", html)


_NON_DISPLAYING_TAGS = build_alternation(
    ["head", "script", "style", "noscript", "xml"], auto_escape=True
)
_RE_NON_DISPLAYING_BLOCKS = re.compile(
    rf"(?is)<(?:{_NON_DISPLAYING_TAGS})\b[^>]*>.*?</(?:{_NON_DISPLAYING_TAGS})>"
)


def strip_non_displaying_blocks(html: str) -> str:
    """Strip script, style, head, noscript, and xml blocks."""
    if (
        "<head" not in html
        and "<HEAD" not in html
        and "<script" not in html
        and "<SCRIPT" not in html
        and "<style" not in html
        and "<STYLE" not in html
        and "<noscript" not in html
        and "<NOSCRIPT" not in html
        and "<xml" not in html
        and "<XML" not in html
    ):
        return html
    return _RE_NON_DISPLAYING_BLOCKS.sub(" ", html)


def clean_html_for_parsing(html: str) -> str:
    """Unified Stage-1 cleaning entry point."""
    html = strip_non_displaying_blocks(html)
    html = strip_ixbrl_inline_tags(html)
    html = normalize_font_qualified_glyphs(html)
    html = strip_benign_font_styles(html)
    html = strip_font_tag_and_noise_attributes(html)
    html = strip_office_metadata_attributes(html)
    html = strip_toc_navigation_links(html)
    return sanitize_unicode_whitespace(html)


# ---------------------------------------------------------------------------
# HTML Structural Decomposer
# ---------------------------------------------------------------------------
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
    dt_content = match.group(1)
    dd_tag = match.group(2)
    clean_dt = _RE_TAG_STRIP.sub("", dt_content).strip()
    if is_list_or_bullet_marker(clean_dt):
        return f"{dd_tag}{clean_dt} "
    return match.group(0)


_HEADING_TERMS_ALT = build_alternation(
    ["item", "part", "section", "rule", "paragraph"], auto_escape=True
)
_RE_HEADING_PREFIX = re.compile(rf"\b(?:{_HEADING_TERMS_ALT})\b$", re.IGNORECASE)


def _collapse_source_whitespace_factory(sentinel_prefix: str, sentinel_suffix: str):
    def _collapse(match: re.Match[str]) -> str:
        text = match.string
        start, end = match.span()
        token = text[start:end]
        if not token.isspace():
            return token
        before = text[max(0, start - 40) : start].rstrip()
        after = text[end : min(len(text), end + 50)].lstrip()
        if before.endswith(sentinel_suffix) or after.startswith(sentinel_prefix):
            return "\n"
        first_token = after.split(maxsplit=1)[0] if after else ""
        if first_token and is_list_or_bullet_marker(first_token):
            if _RE_HEADING_PREFIX.search(before):
                return " "
            return "\n"
        return " "

    return _collapse


def _clean_p_content(match: re.Match[str]) -> str:
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
    """Decompose block and inline HTML tags into normalized plain text."""
    if not html:
        return ""

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

    # 7. Collapse raw source-code line wraps outside tables
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


__all__ = [
    "BLOCK_TAGS",
    "CONTAINER_BLOCK_TAGS",
    "INLINE_TAGS",
    "PARAGRAPH_TAGS",
    "TABLE_AND_PRE_TAGS",
    "clean_html_for_parsing",
    "decompose_html_structures",
    "normalize_font_qualified_glyphs",
    "strip_benign_font_styles",
    "strip_font_tag_and_noise_attributes",
    "strip_ixbrl_inline_tags",
    "strip_non_displaying_blocks",
    "strip_office_metadata_attributes",
    "strip_toc_navigation_links",
]
