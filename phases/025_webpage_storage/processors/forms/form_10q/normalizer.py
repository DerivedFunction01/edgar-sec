"""Form 10-Q family document normalizer."""

from __future__ import annotations

from typing import Any

from defs.sec_forms.cover import get_profile

from ..base import FormNormalizer
from ..shared.headers import FORM_10Q_GRAMMAR, normalize_headers
from ..shared.hybrid_cover import HybridCoverPreprocessor


class Form10QNormalizer(FormNormalizer):
    """Form 10-Q normalizer for cover metadata and structural headings."""

    def preprocess_cover(
        self, html_text: str, metadata: dict[str, Any] | None = None
    ) -> str:
        _ = metadata
        return (
            HybridCoverPreprocessor(get_profile("10-Q"))
            .preprocess(html_text, metadata=metadata)
            .html
        )

    def normalize_headers(
        self, text: str, metadata: dict[str, Any] | None = None
    ) -> str:
        _ = metadata
        return normalize_headers(text, FORM_10Q_GRAMMAR)


__all__ = ["Form10QNormalizer"]
