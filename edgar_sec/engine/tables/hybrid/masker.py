"""Hybrid ``<pre>`` content masking for filings with mixed HTML and ASCII tables.

Transition-era filings embed financial tables inside ``<pre>`` blocks in three
shapes: SGML ``<TABLE><S><C>`` legacy tables, fixed-width monospace columns, and
real ``<table><tr><td>`` markup. A DOM cannot represent the first two faithfully —
literal SGML tags are either parsed as elements or escaped on serialization — so
this module is a text boundary, not a DOM pass. `normalize_hybrid_pre_text`
replaces each ``<pre>`` payload with a private token, ordinary HTML normalization
runs, and `restore_hybrid_pre_text` puts the payload back byte for byte.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from ..ascii_html.converter import convert_html_table

_MONOSPACE_DIVIDER_RE = re.compile(r"^[-=]{3,}\s*$")


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
_PRE_BLOCK_RE = re.compile(r"(?is)<pre\b[^>]*>(?P<body>.*?)</pre\s*>")
_TABLE_RE = re.compile(r"(?is)<table\b.*?</table\s*>")
_TOKEN_PREFIX = "__SEC_HYBRID_PRE_"


@dataclass(frozen=True, slots=True)
class HybridPreText:
    """Text after protecting preformatted payloads from DOM normalization."""

    text: str
    protected: dict[str, str]


def _looks_like_monospace_text(inner: str) -> bool:
    """Heuristic: does the content look like fixed-width columnar text?"""
    stripped = inner.strip()
    if not stripped:
        return False

    lines = stripped.splitlines()
    if len(lines) < 2:
        return False

    dash_lines = sum(
        1 for line in lines if _MONOSPACE_DIVIDER_RE.fullmatch(line.strip())
    )
    if dash_lines >= 1:
        return True

    has_dashes = sum(
        1 for line in lines if "-" in line.strip() and len(line.strip()) > 3
    )
    return has_dashes >= 2


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
        if _TOKEN_PREFIX in text:
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
    """Restore payloads protected by :func:`normalize_hybrid_pre_text`.

    Raises:
        ValueError: a token is absent from ``text``. Restoration is verified,
            not assumed, because a silently dropped payload loses an entire
            financial table.
    """
    if not protected:
        return text
    if len(protected) == 1:
        token, payload = next(iter(protected.items()))
        if token not in text:
            raise ValueError(f"hybrid pre token missing during restore: {token!r}")
        return text.replace(token, payload)

    pattern = re.compile("|".join(re.escape(k) for k in protected))
    seen_tokens: set[str] = set()

    def _replace_token(match: re.Match[str]) -> str:
        t = match.group(0)
        seen_tokens.add(t)
        return protected[t]

    restored = pattern.sub(_replace_token, text)
    missing = set(protected) - seen_tokens
    if missing:
        raise ValueError(
            f"hybrid pre token missing during restore: {next(iter(missing))!r}"
        )
    return restored


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


__all__ = [
    "HybridPreText",
    "PreBlockKind",
    "normalize_hybrid_pre_text",
    "restore_hybrid_pre_text",
]
