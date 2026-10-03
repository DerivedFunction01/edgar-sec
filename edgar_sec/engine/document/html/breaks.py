"""Page-break sentinel injection, applied outside protected table spans.
None of HTML's four page-boundary carriers survives plain-text projection, so each becomes a
sentinel. Substitution skips `<TABLE>` spans, or a decorative `<hr>` becomes cell text.
"""

from __future__ import annotations

import re

from edgar_sec.engine.document.html.normalizer import (
    NormalizedHtmlText,
    normalize_html_document,
)
from edgar_sec.engine.tables.protection.tags import find_table_spans
from edgar_sec.foundation.regex.builder import build_alternation

_BREAK_PROPERTIES = build_alternation(
    ["page-break-before", "page-break-after", "break-before", "break-after"],
    auto_escape=True,
)
_BREAK_VALUES = build_alternation(
    ["always", "page", "all", "left", "right", "recto", "verso"],
    auto_escape=True,
)
_RE_CSS_PAGE_BREAKS = re.compile(
    rf"""<[^>]*style=[\"'][^\"']*(?:{_BREAK_PROPERTIES})\s*:\s*(?:{_BREAK_VALUES})\b[^\"']*[\"'][^>]*>""",
    re.IGNORECASE,
)
_RE_HR_TAGS = re.compile(r"<hr\b[^>]*>", re.IGNORECASE)
_RE_PAGE_TAGS = re.compile(r"</?page\b[^>]*>", re.IGNORECASE)

# Canonical break-role entries for page-hint tokens: class/id names a filing system generates
# for a page boundary. Number-, header-, footer-, and container-role tokens belong to page analysis.
PAGE_BREAK_HINT_TOKENS: tuple[str, ...] = (
    "pagebreak",
    "ctpagebreak",
    "pgbrk",
    "pgbk",
    "pagebreakbefore",
    "pagebreakafter",
    "breakbefore",
    "breakafter",
    "dspfpagebreak",
    "dspfpagebreakarea",
    "lastpagebreak",
)
_BREAK_HINTS_ALT = build_alternation(PAGE_BREAK_HINT_TOKENS, auto_escape=True)
_RE_CLASS_ID_PAGE_BREAKS = re.compile(
    rf"""<[^>]+(?:class|id)=[\"'][^\"']*\b(?:{_BREAK_HINTS_ALT})\b[^\"']*[\"'][^>]*>""",
    re.IGNORECASE,
)

_RE_PAGE_SENTINEL_RUN = re.compile(r"(?:\n\s*<PAGE>\s*)+")

# "SPLIT" deliberately avoids r/R: the glyph pass maps r/R to checkbox glyphs inside
# Wingdings/Webdings/Symbol scopes, corrupting the sentinel.
PAGE_SPLIT_SENTINEL = "__SEC_PAGE_SPLIT_SENTINEL__"

# The canonical marker this sentinel becomes in the ASCII text frame - an internal transport
# form; page-artifact rendering emits `[[SEC:PAGE_BREAK id=N]]` at the artifact boundary.
PAGE_MARKER_LINE = "<PAGE>"

# One combined pattern: the rules share the sentinel replacement and use mutually exclusive tag
# prefixes, so the alternation reproduces applying them sequentially.
_RE_BREAK_TAGS = re.compile(
    f"{_RE_PAGE_TAGS.pattern}|{_RE_HR_TAGS.pattern}"
    f"|{_RE_CSS_PAGE_BREAKS.pattern}|{_RE_CLASS_ID_PAGE_BREAKS.pattern}",
    re.IGNORECASE,
)


def insert_page_sentinels(html: str) -> str:
    """Replace page-break markup with the page-split sentinel, outside tables.
    Returns the input unchanged when it holds no ``<TABLE>`` span.
    """
    replacement = f"\n{PAGE_SPLIT_SENTINEL}\n"
    spans = find_table_spans(html)
    if not spans:
        return _RE_BREAK_TAGS.sub(replacement, html)
    pieces: list[str] = []
    cursor = 0
    for span in spans:
        pieces.append(_RE_BREAK_TAGS.sub(replacement, html[cursor : span.start]))
        pieces.append(html[span.start : span.end])
        cursor = span.end
    pieces.append(_RE_BREAK_TAGS.sub(replacement, html[cursor:]))
    return "".join(pieces)


def collapse_marker_runs(text: str) -> str:
    """Collapse adjacent ``<PAGE>`` marker runs into one.
    Applied after the sentinel has become a marker. A repeated marker is preserved: two breaks in a row are evidence of a blank page.
    """
    return _RE_PAGE_SENTINEL_RUN.sub(f"\n{PAGE_MARKER_LINE}\n", text)


def render_html_to_break_text(html: str) -> NormalizedHtmlText:
    """Project HTML into the text frame, carrying page boundaries across.
    Break markup becomes the transport sentinel before projection, then the canonical ``<PAGE>`` marker; the declared policy decides each marker's fate.
    """
    if not html:
        return NormalizedHtmlText("", ())
    normalized = normalize_html_document(insert_page_sentinels(html))
    converted = collapse_marker_runs(
        str(normalized).replace(PAGE_SPLIT_SENTINEL, f"\n{PAGE_MARKER_LINE}\n")
    )
    return NormalizedHtmlText(converted.strip(), normalized.table_geometries)


__all__ = [
    "PAGE_BREAK_HINT_TOKENS",
    "PAGE_MARKER_LINE",
    "PAGE_SPLIT_SENTINEL",
    "collapse_marker_runs",
    "insert_page_sentinels",
    "render_html_to_break_text",
]
