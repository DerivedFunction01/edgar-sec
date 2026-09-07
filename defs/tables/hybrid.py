"""Hybrid <pre> content discriminator for SEC filings with mixed HTML/ASCII tables.

Transition-era SEC filings (circa 2000-2010) embed financial tables inside
<pre> blocks using three distinct patterns:
  1. SGML <TABLE><S><C> legacy ASCII tables
  2. Fixed-width monospace columnar text
  3. True HTML <table><tr><td> structures

This module classifies each <pre> block and normalizes the DOM tree so that
each pattern is handled correctly without breaking HTML prose or mangling
preformatted ASCII tables.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from defs.tables.ascii_html import convert_html_table
from defs.tables.protection import mask_tagged_tables, restore_tagged_tables
from defs.text.html import FastHtmlNode, FastHtmlTree


class PreBlockKind(str, Enum):
    """Classification of content inside a <pre> block."""

    SGML_TABLE = "sgml_table"
    HTML_TABLE = "html_table"
    MONOSPACE_TEXT = "monospace_text"
    NARRATIVE_PROSE = "narrative_prose"


_SGML_TABLE_RE = re.compile(r"<TABLE\b", re.IGNORECASE)
_S_MARKER_RE = re.compile(r"<S\b", re.IGNORECASE)
_C_MARKER_RE = re.compile(r"<C\b", re.IGNORECASE)
_HTML_TABLE_RE = re.compile(r"<table\b", re.IGNORECASE)
_TR_TD_RE = re.compile(r"<t[dh]\b", re.IGNORECASE)
_PRE_OPEN_RE = re.compile(r"<pre\b[^>]*>", re.IGNORECASE)
_PRE_CLOSE_RE = re.compile(r"</pre\s*>", re.IGNORECASE)
_PRE_BLOCK_RE = re.compile(r"(?is)<pre\b[^>]*>(?P<body>.*?)</pre\s*>")
_TABLE_RE = re.compile(r"(?is)<table\b.*?</table\s*>")
_TOKEN_PREFIX = "__SEC_HYBRID_PRE_"


@dataclass(frozen=True, slots=True)
class HybridPreText:
    """Text after protecting preformatted payloads from DOM normalization."""

    text: str
    protected: dict[str, str]


def classify_pre_block(pre_node: FastHtmlNode) -> PreBlockKind:
    """Classify the content of a <pre> node into one of four kinds.

    Classification logic:
    - SGML_TABLE: Contains <TABLE> with <S>/<C> markers or no <tr>/<td>.
    - HTML_TABLE: Contains <table> with standard <tr>/<td> structure.
    - MONOSPACE_TEXT: Fixed-width columnar text / dashes without <table> tags.
    - NARRATIVE_PROSE: Standard wrapped prose lines.
    """
    raw_html = pre_node.raw_node.html or ""
    inner = _extract_pre_inner(raw_html)

    has_sgml_table = bool(_SGML_TABLE_RE.search(inner))
    has_s_marker = bool(_S_MARKER_RE.search(inner))
    has_c_marker = bool(_C_MARKER_RE.search(inner))
    has_html_table = bool(_HTML_TABLE_RE.search(inner))
    has_tr_td = bool(_TR_TD_RE.search(inner))

    if has_sgml_table and (has_s_marker or has_c_marker or not has_tr_td):
        return PreBlockKind.SGML_TABLE

    if has_html_table and has_tr_td:
        return PreBlockKind.HTML_TABLE

    if has_sgml_table and not has_tr_td:
        return PreBlockKind.SGML_TABLE

    if has_html_table and not has_tr_td:
        return PreBlockKind.SGML_TABLE

    if _looks_like_monospace_text(inner):
        return PreBlockKind.MONOSPACE_TEXT

    return PreBlockKind.NARRATIVE_PROSE


def _extract_pre_inner(raw_html: str) -> str:
    """Extract the inner content of a <pre> block from its raw HTML."""
    match = _PRE_OPEN_RE.search(raw_html)
    if match is None:
        return raw_html
    start = match.end()
    end_match = _PRE_CLOSE_RE.search(raw_html, start)
    if end_match is None:
        return raw_html[start:]
    return raw_html[start : end_match.start()]


def _looks_like_monospace_text(inner: str) -> bool:
    """Heuristic: does the content look like fixed-width columnar text?"""
    stripped = inner.strip()
    if not stripped:
        return False

    lines = stripped.splitlines()
    if len(lines) < 2:
        return False

    dash_lines = sum(1 for line in lines if re.match(r"^[-=]{3,}\s*$", line.strip()))
    if dash_lines >= 1:
        return True

    has_dashes = sum(
        1 for line in lines if "-" in line.strip() and len(line.strip()) > 3
    )
    return has_dashes >= 2


def _insert_raw_html(pre_node: FastHtmlNode, html: str) -> None:
    """Insert raw HTML string before the node and decompose the node.

    Uses insert_before + decompose instead of replace_with to avoid
    selectolax escaping HTML content.
    """
    pre_node.raw_node.insert_before(html)
    pre_node.raw_node.decompose()


def normalize_hybrid_pre_blocks(tree: FastHtmlTree) -> None:
    """Normalize <pre> blocks in the DOM tree based on their content type.

    - HTML_TABLE: Convert the inner <table> via convert_html_table and replace
      the <pre> wrapper with the rendered ASCII table.
    - SGML_TABLE: Unwrap the <pre> tag and mask <TABLE>...</TABLE> spans so
      they are protected from whitespace collapse during later normalization.
    - MONOSPACE_TEXT: Unwrap the <pre> tag preserving verbatim text content.
    - NARRATIVE_PROSE: Unwrap the <pre> tag normally.
    """
    pre_nodes = tree.css("pre")
    for pre_node in pre_nodes:
        kind = classify_pre_block(pre_node)

        if kind == PreBlockKind.HTML_TABLE:
            _convert_html_table_in_pre(pre_node)
        elif kind == PreBlockKind.SGML_TABLE:
            _preserve_sgml_in_pre(pre_node)
        elif kind == PreBlockKind.MONOSPACE_TEXT:
            _preserve_monospace_in_pre(pre_node)
        else:
            pre_node.unwrap()


def normalize_hybrid_pre_text(text: str) -> HybridPreText:
    """Protect hybrid ``<pre>`` payloads before HTML DOM normalization.

    Literal SGML tags are not representable as text in a selectolax DOM: they
    are either parsed as elements or escaped on serialization. This boundary
    function therefore replaces each classified payload with a private token.
    The caller must pass the result to :func:`restore_hybrid_pre_text` after
    normal HTML table conversion has completed.
    """
    protected: dict[str, str] = {}
    pieces: list[str] = []
    cursor = 0

    for index, match in enumerate(_PRE_BLOCK_RE.finditer(text)):
        body = match.group("body")
        kind = _classify_pre_source(body)
        payload = body
        if kind == PreBlockKind.HTML_TABLE:
            table_match = _TABLE_RE.search(body)
            if table_match is not None:
                rendered = convert_html_table(table_match.group(0)).ascii_text
                if rendered:
                    payload = (
                        body[: table_match.start()]
                        + rendered
                        + body[table_match.end() :]
                    )

        token = f"{_TOKEN_PREFIX}{index}__"
        while token in text:
            token += "_"
        protected[token] = payload
        pieces.extend((text[cursor : match.start()], token))
        cursor = match.end()

    if not protected:
        return HybridPreText(text=text, protected={})
    pieces.append(text[cursor:])
    return HybridPreText(text="".join(pieces), protected=protected)


def restore_hybrid_pre_text(text: str, protected: dict[str, str]) -> str:
    """Restore payloads protected by :func:`normalize_hybrid_pre_text`."""
    for token, payload in protected.items():
        if token not in text:
            raise ValueError(f"hybrid pre token missing during restore: {token!r}")
        text = text.replace(token, payload)
    return text


def _classify_pre_source(body: str) -> PreBlockKind:
    """Classify raw pre source without parsing it as HTML."""
    has_table = bool(_TABLE_RE.search(body))
    has_cell_markers = bool(_S_MARKER_RE.search(body) or _C_MARKER_RE.search(body))
    has_html_rows = bool(_TR_TD_RE.search(body))
    if has_table and (has_cell_markers or not has_html_rows):
        return PreBlockKind.SGML_TABLE
    if has_table and has_html_rows:
        return PreBlockKind.HTML_TABLE
    if _looks_like_monospace_text(body):
        return PreBlockKind.MONOSPACE_TEXT
    return PreBlockKind.NARRATIVE_PROSE


def _convert_html_table_in_pre(pre_node: FastHtmlNode) -> None:
    """Convert an HTML <table> inside <pre> to canonical ASCII and replace."""
    inner_html = pre_node.raw_node.html or ""
    table_match = _HTML_TABLE_RE.search(inner_html)
    if table_match is None:
        pre_node.unwrap()
        return

    table_start = table_match.start()
    table_html = inner_html[table_start:]

    try:
        result = convert_html_table(table_html)
        if result.ascii_text:
            _insert_raw_html(pre_node, result.ascii_text)
        else:
            pre_node.unwrap()
    except (ValueError, TypeError):
        pre_node.unwrap()


def _preserve_sgml_in_pre(pre_node: FastHtmlNode) -> None:
    """Unwrap <pre> and protect SGML <TABLE>...</TABLE> spans from collapse."""
    inner_html = pre_node.raw_node.html or ""
    inner = _extract_pre_inner(inner_html)

    masked_text, spans = mask_tagged_tables(inner)
    if spans:
        restored = restore_tagged_tables(masked_text, spans)
        _insert_raw_html(pre_node, restored)
    else:
        _insert_raw_html(pre_node, inner)


def _preserve_monospace_in_pre(pre_node: FastHtmlNode) -> None:
    """Unwrap <pre> preserving verbatim monospace text content."""
    inner_html = pre_node.raw_node.html or ""
    inner = _extract_pre_inner(inner_html)
    _insert_raw_html(pre_node, inner)


__all__ = [
    "HybridPreText",
    "PreBlockKind",
    "classify_pre_block",
    "normalize_hybrid_pre_blocks",
    "normalize_hybrid_pre_text",
    "restore_hybrid_pre_text",
]
