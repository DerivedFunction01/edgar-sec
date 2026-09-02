"""Form 8-K family document normalizer."""

from __future__ import annotations

from typing import Any

from defs.sec_forms.cover import get_profile

from ..base import CoverPreprocessResult, FormNormalizer
from ..shared.headers import FORM_8K_GRAMMAR, normalize_headers
from ..shared.hybrid_cover import HybridCoverPreprocessor


class Form8KNormalizer(FormNormalizer):
    """Form 8-K normalizer for current-report Section/Item headings."""

    def preprocess_cover(
        self, html_text: str, metadata: dict[str, Any] | None = None
    ) -> CoverPreprocessResult:
        _ = metadata
        return HybridCoverPreprocessor(get_profile("8-K")).preprocess(
            html_text, metadata=metadata
        )

    def normalize_headers(
        self, text: str, metadata: dict[str, Any] | None = None
    ) -> str:
        _ = metadata
        return normalize_headers(text, FORM_8K_GRAMMAR)


__all__ = ["Form8KNormalizer"]
