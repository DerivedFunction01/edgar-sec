"""HTML page break sentinel injection outside table spans.

SEC HTML filings represent page boundaries with CSS page-break properties,
horizontal rules (<hr>), explicit <page> tags, or class/id hint tokens.
Break tags inside <table> spans are table formatting (e.g. decorative rules),
not document page breaks. This module substitutes breaks outside tables with
a sentinel so subsequent HTML normalization can preserve them as <PAGE>.
"""

from __future__ import annotations

import re

from edgar_sec.engine.tables.protection import find_table_spans
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

_BREAK_HINT_TOKENS = (
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
_BREAK_HINTS_ALT = build_alternation(
    _BREAK_HINT_TOKENS,
    auto_escape=True,
)
_RE_CLASS_ID_PAGE_BREAKS = re.compile(
    rf"""<[^>]+(?:class|id)=[\"'][^\"']*\b(?:{_BREAK_HINTS_ALT})\b[^\"']*[\"'][^>]*>""",
    re.IGNORECASE,
)

# "SPLIT" deliberately avoids r/R: Stage-1 glyph passes map r/R to
# checkbox glyphs inside Wingdings/Symbol scopes.
PAGE_SENTINEL = "__SEC_PAGE_SPLIT_SENTINEL__"
RE_PAGE_SENTINEL_COLLAPSE = re.compile(r"(?:\n\s*<PAGE>\s*)+")

_RE_BREAK_TAGS = re.compile(
    build_alternation(
        [
            _RE_PAGE_TAGS.pattern,
            _RE_HR_TAGS.pattern,
            _RE_CSS_PAGE_BREAKS.pattern,
            _RE_CLASS_ID_PAGE_BREAKS.pattern,
        ]
    ),
    re.IGNORECASE,
)


def insert_page_sentinels(html: str) -> str:
    """Replace break tags with the page-split sentinel outside table spans.

    Break tags inside tables are page furniture (e.g. <hr> lines in tables),
    not page boundaries. Converting them inside tables would corrupt the table
    layout.
    """
    if not html:
        return ""
    replacement = f"\n{PAGE_SENTINEL}\n"
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


def convert_sentinels_to_page_markers(text: str) -> str:
    """Convert page sentinels into normalized ASCII <PAGE> markers."""
    if not text:
        return ""
    collapsed = RE_PAGE_SENTINEL_COLLAPSE.sub(
        f"\n{PAGE_SENTINEL}\n",
        text,
    )
    converted = collapsed.replace(PAGE_SENTINEL, "\n<PAGE>\n")
    return RE_PAGE_SENTINEL_COLLAPSE.sub("\n<PAGE>\n", converted).strip()


__all__ = [
    "PAGE_SENTINEL",
    "convert_sentinels_to_page_markers",
    "insert_page_sentinels",
]
