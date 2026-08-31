"""Deep document normalization and form-aware SEC content standardization."""

from __future__ import annotations

import re
from typing import Any

from defs.regex import build_alternation
from defs.tables import convert_html_tables_to_ascii

from .forms.base import PreprocessedDocument
from .router import FormRouter

_RE_PAGE_TAG = re.compile(r"(?i)<\/?PAGE\b[^>]*>")
_RE_PAGE_NUM_FOOTER = re.compile(
    r"(?im)^\s*(?:page\s+\d+(?:\s+of\s+\d+)?|\d+\s+of\s+\d+|-\s*\d+\s*-)\s*$"
)
_IXBRL_PREFIXES = build_alternation(["ix", "xbrli", "dei", "us-gaap"])
_RE_XML_IXBRL_TAGS = re.compile(rf"</?(?:{_IXBRL_PREFIXES}):[^>]*>", re.IGNORECASE)
_RE_MULTIPLE_BLANKS = re.compile(r"\n{3,}")
_RE_TRAILING_WHITESPACE = re.compile(r"[ \t]+$", re.MULTILINE)
_RE_TOC_LEADER_DOTS = re.compile(r"(?:\s*\.\s*){5,}\s*(?=\d+\b)")


class DeepNormalizer:
    """Stage 3 normalizer; coordinates generic table and form-aware structural normalization."""

    def __init__(self, router: FormRouter | None = None) -> None:
        self._router = router or FormRouter()

    def normalize(
        self,
        preprocessed: PreprocessedDocument,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Normalize preprocessed document using form-specific and generic rules."""
        form = (metadata or {}).get("form") or preprocessed.metadata.get("form")
        form_normalizer = self._router.get_normalizer(form)

        # 1. Form-specific HTML cover-page preprocessing
        text = preprocessed.cleaned_text
        if preprocessed.has_html_tags and "<table" in text.lower():
            text = form_normalizer.preprocess_cover(text, metadata)

        # 2. Generic HTML financial table to ASCII conversion & HTML tag stripping
        if preprocessed.has_html_tags and "<TABLE>" not in text:
            text = convert_html_tables_to_ascii(text)

        # 3. Invariant generic cleanup passes
        text = _RE_XML_IXBRL_TAGS.sub("", text)
        text = _RE_PAGE_TAG.sub("\n", text)
        text = _RE_PAGE_NUM_FOOTER.sub("", text)

        # 4. Form-specific heading standardization
        text = form_normalizer.normalize_headers(text, metadata)

        # 5. Final whitespace & TOC cleanup
        text = _RE_TOC_LEADER_DOTS.sub("  ", text)
        text = _RE_TRAILING_WHITESPACE.sub("", text)
        text = _RE_MULTIPLE_BLANKS.sub("\n\n", text)
        return text.strip()


__all__ = ["DeepNormalizer"]
