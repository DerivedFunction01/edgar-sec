"""Form 10-K family document normalizer."""

from __future__ import annotations

from typing import Any

from defs.sec_forms.cover import get_profile

from ..base import CoverPreprocessResult, FormNormalizer
from ..shared.headers import FORM_10K_GRAMMAR, normalize_headers
from ..shared.hybrid_cover import HybridCoverPreprocessor


class Form10KNormalizer(FormNormalizer):
    """Form 10-K normalizer for cover metadata and structural headings."""

    def preprocess_cover(
        self,
        html_text: str,
        metadata: dict[str, Any] | None = None,
        page_analysis=None,
    ) -> CoverPreprocessResult:
        meta = metadata or {}
        company_name = meta.get("company_name") or meta.get("input_name") or ""
        return HybridCoverPreprocessor(get_profile("10-K")).preprocess(
            html_text,
            company_name=company_name,
            metadata=meta,
            page_analysis=page_analysis,
        )

    def normalize_headers(
        self, text: str, metadata: dict[str, Any] | None = None
    ) -> str:
        _ = metadata
        return normalize_headers(text, FORM_10K_GRAMMAR)


__all__ = ["Form10KNormalizer"]
