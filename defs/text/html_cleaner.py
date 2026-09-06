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

# ---------------------------------------------------------------------------
# Inline XBRL wrappers
# ---------------------------------------------------------------------------

# The ix:header block is pure XBRL metadata (contexts, units, hidden facts)
# and must be dropped whole before unwrapping the inline tags.
_RE_IX_HEADER_BLOCK = re.compile(r"(?is)<ix:header\b.*?</ix:header>")
_RE_IX_HIDDEN_BLOCK = re.compile(r"(?is)<ix:hidden\b.*?</ix:hidden>")
_RE_IX_OPEN_TAG = re.compile(r"(?i)<ix:[a-z][a-z0-9_.-]*[^>]*>")
_RE_IX_CLOSE_TAG = re.compile(r"(?i)</ix:[a-z][a-z0-9_.-]*\s*>")
_RE_XBRL_OPEN_TAG = re.compile(r"(?i)<xbrli?:[a-z][a-z0-9_.-]*[^>]*>")
_RE_XBRL_CLOSE_TAG = re.compile(r"(?i)</xbrli?:[a-z][a-z0-9_.-]*\s*>")

# ---------------------------------------------------------------------------
# Benign font styles inside style="..." attribute values
# ---------------------------------------------------------------------------

# Standard families carry no downstream signal; symbolic fonts do.
_PRESERVED_FAMILIES = ("wingdings", "webdings", "symbol")
_RE_FONT_FAMILY_DECL = re.compile(
    r"(?i)(?<![a-z-])font-family\s*:\s*(?![^;\"'\n]*(?:"
    + "|".join(_PRESERVED_FAMILIES)
    + r"))[^;\"'\n]*;?"
)
_RE_FONT_SIZE_DECL = re.compile(r"(?i)(?<![a-z-])font-size\s*:[^;\"'\n]*;?")
_RE_COLOR_DECL = re.compile(r"(?i)(?<![a-z-])(?:background-)?color\s*:[^;\"'\n]*;?")
# Repeated separators and empty declarations left behind by the passes above.
_RE_REDUNDANT_SEPARATORS = re.compile(r";\s*;")
_RE_EMPTY_STYLE_ATTR = re.compile(r'(?i)(?<=[\s"])style\s*=\s*"\s*"')

# ---------------------------------------------------------------------------
# Office / transport metadata attributes
# ---------------------------------------------------------------------------

_RE_METADATA_ATTR_DQ = re.compile(
    r'(?i)\s+(?:mso|data)-[a-z0-9_.-]+\s*=\s*"[^"]*"'
    r'|\s+xml:lang\s*=\s*"[^"]*"'
    r'|\s+lang\s*=\s*"[^"]*"'
)
_RE_METADATA_ATTR_SQ = re.compile(
    r"(?i)\s+(?:mso|data)-[a-z0-9_.-]+\s*=\s*'[^']*'"
    r"|\s+xml:lang\s*=\s*'[^']*'"
    r"|\s+lang\s*=\s*'[^']*'"
)


def strip_ixbrl_inline_tags(html: str) -> str:
    """Unwrap inline XBRL tags while keeping their inner text content."""
    if "ix:" not in html and "xbrl" not in html and "xbrli" not in html:
        return html
    html = _RE_IX_HEADER_BLOCK.sub(" ", html)
    html = _RE_IX_HIDDEN_BLOCK.sub(" ", html)
    html = _RE_IX_OPEN_TAG.sub("", html)
    html = _RE_IX_CLOSE_TAG.sub("", html)
    html = _RE_XBRL_OPEN_TAG.sub("", html)
    html = _RE_XBRL_CLOSE_TAG.sub("", html)
    return html


def strip_benign_font_styles(html: str) -> str:
    """Strip redundant standard font declarations from style attributes.

    Symbolic fonts (Wingdings, Webdings, Symbol) are preserved because
    downstream checkbox normalization keys on them.  Structural style
    declarations (borders, alignment, width) are never touched.
    """
    if "style=" not in html:
        return html
    html = _RE_FONT_FAMILY_DECL.sub("", html)
    html = _RE_FONT_SIZE_DECL.sub("", html)
    html = _RE_COLOR_DECL.sub("", html)
    html = _RE_REDUNDANT_SEPARATORS.sub(";", html)
    return _RE_EMPTY_STYLE_ATTR.sub("", html)


def strip_office_metadata_attributes(html: str) -> str:
    """Strip ``mso-*``, ``data-*``, ``xml:lang``, and ``lang`` attributes."""
    if "mso-" not in html and "data-" not in html and "lang=" not in html:
        return html
    html = _RE_METADATA_ATTR_DQ.sub("", html)
    return _RE_METADATA_ATTR_SQ.sub("", html)


def clean_html_for_parsing(html: str) -> str:
    """Unified Stage-1 cleaning entry point.

    Composes the passes in dependency order: inline XBRL wrappers first (they
    carry their own style attributes), then benign font styles, then metadata
    attributes (some ``mso-*`` values only exist on tags that survived the
    font pass).
    """
    html = strip_ixbrl_inline_tags(html)
    html = strip_benign_font_styles(html)
    return strip_office_metadata_attributes(html)
