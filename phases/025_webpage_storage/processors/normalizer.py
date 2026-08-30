"""Deep document normalization and SEC heading standardization."""

from __future__ import annotations

import re
from typing import Any

from defs.regex import build_alternation
from defs.tables import convert_html_tables_to_ascii

from .forms.base import PreprocessedDocument

_RE_PAGE_TAG = re.compile(r"(?i)<\/?PAGE\b[^>]*>")
_RE_PAGE_NUM_FOOTER = re.compile(
    r"(?im)^\s*(?:page\s+\d+(?:\s+of\s+\d+)?|\d+\s+of\s+\d+|-\s*\d+\s*-)\s*$"
)
_IXBRL_PREFIXES = build_alternation(["ix", "xbrli", "dei", "us-gaap"])
_RE_XML_IXBRL_TAGS = re.compile(rf"</?(?:{_IXBRL_PREFIXES}):[^>]*>", re.IGNORECASE)
_RE_MULTIPLE_BLANKS = re.compile(r"\n{3,}")
_RE_TRAILING_WHITESPACE = re.compile(r"[ \t]+$", re.MULTILINE)
_RE_TOC_LEADER_DOTS = re.compile(r"(?:\s*\.\s*){5,}\s*(?=\d+\b)")
_RE_ITEM_HEADER = re.compile(
    r"(?im)^\s*(item\s+(?:1[0-5]?|[1-9])[a-z]?)\s*[\.:\-–—]\s*(.*?)\s*$"
)
_PART_NUMS = build_alternation([r"i{1,4}", "iv", "v"])
_RE_PART_HEADER = re.compile(rf"(?im)^\s*(part\s+(?:{_PART_NUMS}))\s*[\.:\-–—]?\s*$")


class DeepNormalizer:
    """Stage 3 normalizer; shared tables owns all HTML table behavior."""

    def normalize(
        self,
        preprocessed: PreprocessedDocument,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        _ = metadata
        text = preprocessed.cleaned_text
        if preprocessed.has_html_tags and "<table" in text.lower():
            text = convert_html_tables_to_ascii(text)
        text = _RE_XML_IXBRL_TAGS.sub("", text)
        text = _RE_PAGE_TAG.sub("\n", text)
        text = _RE_PAGE_NUM_FOOTER.sub("", text)
        text = self._normalize_headers(text)
        text = _RE_TOC_LEADER_DOTS.sub("  ", text)
        text = _RE_TRAILING_WHITESPACE.sub("", text)
        text = _RE_MULTIPLE_BLANKS.sub("\n\n", text)
        return text.strip()

    def _normalize_headers(self, text: str) -> str:
        """Standardize SEC Part and Item headings."""

        def replace_part(match: re.Match[str]) -> str:
            return f"\n\n{match.group(1).upper()}\n"

        def replace_item(match: re.Match[str]) -> str:
            title = match.group(2).strip()
            suffix = f". {title}" if title else "."
            return f"\n\n{match.group(1).upper()}{suffix}\n"

        return _RE_ITEM_HEADER.sub(
            replace_item, _RE_PART_HEADER.sub(replace_part, text)
        )
