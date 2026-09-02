"""Generic preprocessor shared across all form types.

Handles encoding decoding, XML/HTML entity unescaping, and lightweight preliminary
normalization.
"""

from __future__ import annotations

import html
import re
from typing import Any

from defs.regex import build_alternation
from defs.sec_forms.page_markers import analyze_page_markers

from .forms.base import PreprocessedDocument

# Fast regexes for envelope and structural markers
_TAG_NAMES = build_alternation(["script", "style", "head"])
_RE_HEAD_SCRIPT_STYLE = re.compile(
    rf"(?is)<(?:{_TAG_NAMES})\b[^>]*>.*?</(?:{_TAG_NAMES})>"
)
_RE_DOCUMENT_WRAPPER = re.compile(
    r"(?is)^\s*<DOCUMENT>\s*(?:<TYPE>.*?\n)?(?:<SEQUENCE>.*?\n)?(?:<FILENAME>.*?\n)?(?:<DESCRIPTION>.*?\n)?<TEXT>\s*(.*?)\s*</TEXT>\s*</DOCUMENT>\s*$"
)

# HTML structural and styling tag discriminators (excludes SGML ASCII <TABLE><S><C>)
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


class GenericPreprocessor:
    """Stage 1 generic preprocessor for raw document bytes."""

    @staticmethod
    def decode_bytes(raw_bytes: bytes) -> tuple[str, str]:
        """Safely decode raw bytes into a string representation with detected encoding."""
        if not raw_bytes:
            return "", "utf-8"

        # 1. Try UTF-8
        try:
            return raw_bytes.decode("utf-8"), "utf-8"
        except UnicodeDecodeError:
            pass

        # 2. Try Windows-1252 (common in legacy EDGAR desktop submissions)
        try:
            return raw_bytes.decode("cp1252"), "cp1252"
        except UnicodeDecodeError:
            pass

        # 3. Fallback to Latin-1 (guaranteed to decode any byte stream)
        return raw_bytes.decode("latin-1", errors="replace"), "latin-1"

    def preprocess(
        self,
        raw_bytes: bytes,
        metadata: dict[str, Any] | None = None,
    ) -> PreprocessedDocument:
        """Preprocess raw document payload into normalized intermediate text."""
        raw_text, encoding = self.decode_bytes(raw_bytes)
        meta = dict(metadata or {})

        # Strip outer SGML <DOCUMENT>...</DOCUMENT> wrapper if present
        m_doc = _RE_DOCUMENT_WRAPPER.match(raw_text.strip())
        content_text = m_doc.group(1) if m_doc else raw_text

        # Robust HTML discrimination (never matches pure SEC ASCII <TABLE><S><C>)
        has_html = bool(_RE_HTML_DISCRIMINATOR.search(content_text))

        # Strip non-displaying script and style blocks
        clean = _RE_HEAD_SCRIPT_STYLE.sub(" ", content_text)

        # Unescape standard HTML and XML entities (&nbsp;, &amp;, &#160;, etc.)
        clean = html.unescape(clean)

        # Compute preliminary word count
        words = clean.split()
        word_count = len(words)

        page_analysis = analyze_page_markers(
            clean,
            representation="html" if has_html else "ascii",
        )

        return PreprocessedDocument(
            raw_text=raw_text,
            cleaned_text=clean,
            word_count=word_count,
            has_html_tags=has_html,
            detected_encoding=encoding,
            metadata=meta,
            page_analysis=page_analysis,
        )
