"""Deep document normalization and form-aware SEC content standardization."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from defs.regex import build_alternation
from defs.sec_forms.cover import (
    BoundaryInput,
    CoverBoundary,
    find_cover_boundary_for_profile,
    get_profile,
)
from defs.sec_forms.page_markers import strip_page_markers
from defs.tables import convert_html_tables_to_ascii

from .forms.base import PreprocessedDocument
from .router import FormRouter

_IXBRL_PREFIXES = build_alternation(["ix", "xbrli", "dei", "us-gaap"])
_RE_XML_IXBRL_TAGS = re.compile(rf"</?(?:{_IXBRL_PREFIXES}):[^>]*>", re.IGNORECASE)
_RE_MULTIPLE_BLANKS = re.compile(r"\n{3,}")
_RE_TRAILING_WHITESPACE = re.compile(r"[ \t]+$", re.MULTILINE)


@dataclass(frozen=True, slots=True)
class NormalizationResult:
    """Normalized text plus structural metadata discovered during processing."""

    text: str
    cover_boundary: CoverBoundary


class DeepNormalizer:
    """Stage 3 normalizer; coordinates generic table and form-aware structural normalization."""

    def __init__(self, router: FormRouter | None = None) -> None:
        self._router = router or FormRouter()

    def normalize(
        self,
        preprocessed: PreprocessedDocument,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        return self.normalize_result(preprocessed, metadata).text

    def normalize_result(
        self,
        preprocessed: PreprocessedDocument,
        metadata: dict[str, Any] | None = None,
    ) -> NormalizationResult:
        """Normalize preprocessed document using form-specific and generic rules."""
        form = (metadata or {}).get("form") or preprocessed.metadata.get("form")
        form_normalizer = self._router.get_normalizer(form)
        profile = get_profile(form)
        boundary = find_cover_boundary_for_profile(
            BoundaryInput(preprocessed.cleaned_text), profile
        )

        # 1. Form-specific HTML cover-page preprocessing
        text = preprocessed.cleaned_text
        if preprocessed.has_html_tags and "<table" in text.lower():
            cover_result = form_normalizer.preprocess_cover(text, metadata)
            text = cover_result.html
            boundary = cover_result.cover_boundary
        elif not preprocessed.has_html_tags:
            boundary = find_cover_boundary_for_profile(
                BoundaryInput(text, representation="ascii"), profile
            )
        else:
            # HTML without tables: run cover-boundary detection even though
            # there are no layout tables to convert.
            boundary = find_cover_boundary_for_profile(
                BoundaryInput(text, representation="html"), profile
            )

        # 2. Generic HTML financial table to ASCII conversion & HTML tag stripping
        # Meant for html documents that actually are just SGML ASCII documents in the 2008-range that uses <PRE> wrappers
        if preprocessed.has_html_tags and "<TABLE>" not in text:
            text = convert_html_tables_to_ascii(text)

        # 3. Invariant generic cleanup passes
        text = _RE_XML_IXBRL_TAGS.sub("", text)
        text = strip_page_markers(text, preprocessed.page_analysis)

        # 4. Form-specific heading standardization
        text = form_normalizer.normalize_headers(text, metadata)

        # 5. Final whitespace cleanup
        text = _RE_TRAILING_WHITESPACE.sub("", text)
        text = _RE_MULTIPLE_BLANKS.sub("\n\n", text)
        return NormalizationResult(text=text.strip(), cover_boundary=boundary)


__all__ = ["DeepNormalizer", "NormalizationResult"]
