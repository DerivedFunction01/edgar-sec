"""High-throughput Stage-1 HTML pre-cleaning for EDGAR documents.

Removes transport and presentation noise that carries no parsing signal:
inline XBRL wrapper tags, redundant standard font declarations, and Office
metadata attributes.  Every pass is a pre-compiled, structurally scoped regex
so the cleaner adds only a few percent to preprocessing while shrinking the
DOM handed to Stage 2 (page-marker analysis, cover routing, deep
normalization, table conversion).

Preserved on purpose: ``Wingdings`` / ``Webdings`` / ``Symbol`` font
declarations (checkbox normalization depends on them), ``colspan`` /
``rowspan``, borders, ``align`` / ``text-align`` / ``width`` (page-marker
layout routes and table structure depend on them), and all text content.
"""

from __future__ import annotations

import re

from defs.regex import build_alternation
from defs.text.checkmarks import (
    CANONICAL_CHECKED,
    CANONICAL_UNCHECKED,
    font_glyph_state,
)
from defs.text.unicode import sanitize_unicode_whitespace

# ---------------------------------------------------------------------------
# Inline XBRL wrappers
# ---------------------------------------------------------------------------

# The ix:header block is pure XBRL metadata (contexts, units, hidden facts)
# and must be dropped whole before unwrapping the inline tags.
_RE_IX_HEADER_BLOCK = re.compile(r"(?is)<ix:header\b.*?</ix:header>")
_RE_IX_HIDDEN_BLOCK = re.compile(r"(?is)<ix:hidden\b.*?</ix:hidden>")
_IXBRL_PREFIXES = build_alternation(["ix", "xbrl", "xbrli", "dei", "us-gaap"])
_RE_IXBRL_OPEN_TAG = re.compile(rf"(?i)<(?:{_IXBRL_PREFIXES}):[a-z][a-z0-9_.-]*[^>]*>")
_RE_IXBRL_CLOSE_TAG = re.compile(rf"(?i)</(?:{_IXBRL_PREFIXES}):[a-z][a-z0-9_.-]*\s*>")

# ---------------------------------------------------------------------------
# Benign font styles inside style="..." attribute values
# ---------------------------------------------------------------------------

# Standard families carry no downstream signal; symbolic fonts do.
_PRESERVED_FAMILIES = ("wingdings", "webdings", "symbol")
_PRESERVED_FAMILIES_ALT = build_alternation(_PRESERVED_FAMILIES, auto_escape=True)

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

# Single combined style declaration regex: strips non-semantic typography,
# font, margin, padding, color, and flow properties in one fast pass while
# preserving structural borders, alignment, widths, page breaks, and symbol fonts.
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

# Repeated separators and empty declarations left behind by the passes above.
_RE_REDUNDANT_SEPARATORS = re.compile(r";\s*;")
_RE_EMPTY_STYLE_ATTR = re.compile(r'(?i)(?<=[\s"])style\s*=\s*"\s*"')

_RE_TAG_OR_TEXT = re.compile(r"(?is)<!--.*?-->|<[^>]*>|[^<]+")
_RE_STYLE_FONT_FAMILY = re.compile(r"(?i)\bfont-family\s*:\s*([^;\"]+)")
_RE_FACE_ATTR = re.compile(r"(?i)\bface\s*=\s*(?:\"([^\"]*)\"|'([^']*)'|([^\s>]+))")
_RE_TAG_NAME = re.compile(r"(?is)^\s*<\s*(/?)\s*([a-z][a-z0-9:-]*)")
_RE_GLYPH = re.compile(r"[\u00a8\u00fe\u00fd\u0072\u0052]")
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


def _replace_font_glyphs(text: str, font_family: str) -> str:
    def replace(match: re.Match[str]) -> str:
        state = font_glyph_state(font_family, match.group(0))
        if state == "checked":
            return CANONICAL_CHECKED
        if state == "unchecked":
            return CANONICAL_UNCHECKED
        return match.group(0)

    return _RE_GLYPH.sub(replace, text)


# ---------------------------------------------------------------------------
# Presentation <font> attributes and non-semantic HTML attributes
# ---------------------------------------------------------------------------
_FONT_FACE_NOT_SYMBOL = (
    rf"(?:[\"']\s*(?!(?:{_PRESERVED_FAMILIES_ALT})\b)[^>\"']*[\"']|"
    rf"(?!(?:{_PRESERVED_FAMILIES_ALT})\b)[^>\s\"']+)"
)
_RE_NON_SYMBOL_FONT_FACE = re.compile(rf"(?i)\s+face={_FONT_FACE_NOT_SYMBOL}")

_SIZE_COLOR_ALT = build_alternation(["size", "color"], auto_escape=True)
_RE_FONT_SIZE_COLOR_ATTRS = re.compile(
    rf"(?i)\s+(?:{_SIZE_COLOR_ALT})=(?:[\"'][^>\"']*[\"']|[^>\s\"']+)"
)

_NOISE_ATTRS_ALT = build_alternation(
    ["tabindex", "target", "shape", "coords"], auto_escape=True
)
_RE_NOISE_ATTRS = re.compile(
    rf"(?i)\s+(?:{_NOISE_ATTRS_ALT})=(?:[\"'][^>\"']*[\"']|[^>\s\"']+)"
)

# ---------------------------------------------------------------------------
# Office / transport metadata attributes
# ---------------------------------------------------------------------------

_METADATA_PREFIX_ALT = build_alternation(["mso", "data"], auto_escape=True)
_METADATA_LANG_ALT = build_alternation(["xml:lang", "lang"], auto_escape=True)

_RE_METADATA_ATTR_DQ = re.compile(
    rf'(?i)\s+(?:{_METADATA_PREFIX_ALT})-[a-z0-9_.-]+\s*=\s*"[^"]*"'
    rf'|\s+(?:{_METADATA_LANG_ALT})\s*=\s*"[^"]*"'
)
_RE_METADATA_ATTR_SQ = re.compile(
    rf"(?i)\s+(?:{_METADATA_PREFIX_ALT})-[a-z0-9_.-]+\s*=\s*'[^']*'"
    rf"|\s+(?:{_METADATA_LANG_ALT})\s*=\s*'[^']*'"
)


def strip_ixbrl_inline_tags(html: str) -> str:
    """Unwrap inline XBRL tags while keeping their inner text content."""
    if ":" not in html:
        return html
    html = _RE_IX_HEADER_BLOCK.sub(" ", html)
    html = _RE_IX_HIDDEN_BLOCK.sub(" ", html)
    html = _RE_IXBRL_OPEN_TAG.sub("", html)
    html = _RE_IXBRL_CLOSE_TAG.sub("", html)
    return html


def normalize_font_qualified_glyphs(html: str) -> str:
    """Map only glyphs in text nodes with an explicit symbolic font.

    This scanner deliberately leaves tags, attributes, comments, scripts, and
    styles untouched.  A nested font declaration replaces the inherited
    declaration, so ordinary text in an override cannot be reinterpreted.
    """
    if not html:
        return html
    folded_html = html.lower()
    if not any(family in folded_html for family in _PRESERVED_FAMILIES):
        return html

    output: list[str] = []
    font_stack: list[str | None] = []
    current_font: str | None = None
    opaque_depth = 0
    for match in _RE_TAG_OR_TEXT.finditer(html):
        token = match.group(0)
        if not token.startswith("<"):
            if opaque_depth or current_font is None:
                output.append(token)
                continue

            output.append(_replace_font_glyphs(token, current_font or ""))
            continue

        if token.startswith("<!--"):
            output.append(token)
            continue
        tag_match = _RE_TAG_NAME.match(token)
        if tag_match is None:
            output.append(token)
            continue
        closing, tag_name = tag_match.groups()
        tag_name = tag_name.lower()
        if closing:
            output.append(token)
            if tag_name in {"script", "style"} and opaque_depth:
                opaque_depth -= 1
            if font_stack:
                current_font = font_stack.pop()
            continue

        output.append(token)
        if tag_name in {"script", "style"}:
            opaque_depth += 1
        if tag_name in _VOID_TAGS or token.rstrip().endswith("/>"):
            continue
        font_stack.append(current_font)
        style_match = _RE_STYLE_FONT_FAMILY.search(token)
        face_match = _RE_FACE_ATTR.search(token)
        if style_match:
            current_font = style_match.group(1).strip()
        elif face_match:
            current_font = next(
                (value for value in face_match.groups() if value is not None), ""
            ).strip()

    return "".join(output)


def strip_benign_font_styles(html: str) -> str:
    """Strip redundant standard font and layout declarations from style attributes.

    Symbolic fonts (Wingdings, Webdings, Symbol) are preserved because
    downstream checkbox normalization keys on them. Structural style
    declarations (borders, alignment, width, page-breaks, display:none)
    are never touched.
    """
    if "style=" not in html and "style =" not in html:
        return html
    html = _RE_BENIGN_STYLE_DECL.sub("", html)
    html = _RE_REDUNDANT_SEPARATORS.sub(";", html)
    return _RE_EMPTY_STYLE_ATTR.sub("", html)


def strip_office_metadata_attributes(html: str) -> str:
    """Strip ``mso-*``, ``data-*``, ``xml:lang``, and ``lang`` attributes."""
    if "mso-" not in html and "data-" not in html and "lang=" not in html:
        return html
    html = _RE_METADATA_ATTR_DQ.sub("", html)
    return _RE_METADATA_ATTR_SQ.sub("", html)


def strip_font_tag_and_noise_attributes(html: str) -> str:
    """Strip legacy non-symbolic font face/size/color and noise attributes."""
    if "<font" in html or "<FONT" in html:
        html = _RE_NON_SYMBOL_FONT_FACE.sub("", html)
        html = _RE_FONT_SIZE_COLOR_ATTRS.sub("", html)
    if (
        "tabindex=" in html
        or "target=" in html
        or "shape=" in html
        or "coords=" in html
    ):
        html = _RE_NOISE_ATTRS.sub("", html)
    return html


def clean_html_for_parsing(html: str) -> str:
    """Unified Stage-1 cleaning entry point.

    Composes the passes in dependency order: inline XBRL wrappers first (they
    carry their own style attributes), then benign font and layout styles, then
    font tag attributes, then metadata attributes, then Unicode whitespace
    sanitization.
    """
    html = strip_ixbrl_inline_tags(html)
    html = normalize_font_qualified_glyphs(html)
    html = strip_benign_font_styles(html)
    html = strip_font_tag_and_noise_attributes(html)
    html = strip_office_metadata_attributes(html)
    return sanitize_unicode_whitespace(html)
