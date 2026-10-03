"""Input preparation: decode, unwrap the envelope, classify the representation.
ASCII-PRE must be identified before HTML cleaning, which would lose the hard line breaks reflow
depends on. Order is otherwise decode, unwrap, purge, classify, clean.
"""

from __future__ import annotations

import html as html_lib
import re
from enum import StrEnum

from edgar_sec.engine.document.html.cleaner import (
    clean_html_for_parsing,
    strip_non_displaying_blocks,
)
from edgar_sec.engine.document.unpacking.ascii_pre import extract_ascii_pre
from edgar_sec.engine.document.unpacking.unpacker import (
    extract_target_sub_document,
    has_sgml_documents,
    strip_pem_envelope,
)
from edgar_sec.foundation.regex.builder import build_alternation

_NON_DISPLAYING_TAGS = build_alternation(["script", "style", "head"])
_RE_HEAD_SCRIPT_STYLE = re.compile(
    rf"(?is)<(?:{_NON_DISPLAYING_TAGS})\b[^>]*>.*?</(?:{_NON_DISPLAYING_TAGS})>"
)

# Structural and styling discriminators, deliberately excluding the SGML ASCII `<TABLE>`/`<S>`/`<C>`
# shapes: an untagged ASCII statement full of those is not HTML.
_HTML_TAG_NAMES = build_alternation(
    [
        r"!doctype",
        "html",
        "body",
        "div",
        "span",
        "font",
        "tr",
        "td",
        "th",
        "head",
        "style",
        "script",
        "br",
        "p",
        "a",
        "hr",
        "img",
        "ix",
        "xbrl",
    ]
)
_RE_HTML_DISCRIMINATOR = re.compile(rf"(?i)<\/?(?:{_HTML_TAG_NAMES})\b")


class Representation(StrEnum):
    """How a payload's visible content is encoded."""

    ASCII_PLAIN = "ascii"
    ASCII_PRE = "ascii_pre"
    HTML = "html"


def decode_bytes(raw_bytes: bytes) -> tuple[str, str]:
    """Decode raw payload bytes, reporting the encoding that succeeded.
    CP1252 precedes Latin-1 because historical EDGAR desktop submissions are CP1252 far more often, and Latin-1 cannot fail, so it is the terminal fallback.
    """
    if not raw_bytes:
        return "", "utf-8"
    try:
        return raw_bytes.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        pass
    try:
        return raw_bytes.decode("cp1252"), "cp1252"
    except UnicodeDecodeError:
        pass
    return raw_bytes.decode("latin-1", errors="replace"), "latin-1"


def strip_sgml_document_wrapper(raw_text: str) -> str:
    """Extract the inner ``<TEXT>`` of an SGML ``<DOCUMENT>`` wrapper."""
    stripped = raw_text.lstrip()
    if not stripped.upper().startswith("<DOCUMENT>"):
        return raw_text
    upper = raw_text.upper()
    start_pos = upper.find("<TEXT>")
    end_pos = upper.rfind("</TEXT>")
    if start_pos != -1 and end_pos != -1 and end_pos > start_pos:
        doc_end = upper.find("</DOCUMENT>", end_pos)
        if doc_end != -1:
            return raw_text[start_pos + 6 : end_pos].strip()
    return raw_text


def strip_envelope_text(text: str) -> str:
    """Strip PEM and SGML transport envelopes from a payload that reached here whole.
    Defense in depth: without it a raw bundle handed straight to the normalizer shows ``<DOCUMENT>`` framing.
    """
    raw = text.encode("latin-1", errors="replace")
    stripped = strip_pem_envelope(raw)
    if not has_sgml_documents(stripped):
        return strip_sgml_document_wrapper(stripped.decode("latin-1"))
    selected = extract_target_sub_document(
        stripped,
        target_types=(),
        primary_filename=None,
        fallback_to_sequence_one=True,
    )
    if selected is not None:
        return selected.decode("latin-1")
    return strip_sgml_document_wrapper(stripped.decode("latin-1"))


def prepare_input_text(raw_bytes: bytes) -> tuple[str, Representation, str]:
    """Decode, unwrap, purge, classify, and clean one payload.
    Returns ``(cleaned_text, representation, encoding)``. Never raises on malformed input.
    """
    raw_text, encoding = decode_bytes(raw_bytes)
    content = strip_envelope_text(raw_text)
    content = strip_non_displaying_blocks(content)

    ascii_pre = extract_ascii_pre(content)
    if ascii_pre is not None:
        return html_lib.unescape(ascii_pre), Representation.ASCII_PRE, encoding

    has_html = bool(_RE_HTML_DISCRIMINATOR.search(content))
    if not has_html:
        return html_lib.unescape(content), Representation.ASCII_PLAIN, encoding

    return (
        clean_html_for_parsing(content),
        Representation.HTML,
        encoding,
    )


__all__ = [
    "Representation",
    "decode_bytes",
    "prepare_input_text",
    "strip_envelope_text",
    "strip_sgml_document_wrapper",
]
