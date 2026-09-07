"""Form 10-K family document normalizer."""

from __future__ import annotations

from typing import Any

from ..base import FormNormalizer
from ..shared.headers import FORM_10K_GRAMMAR, normalize_headers


class Form10KNormalizer(FormNormalizer):
    """Form 10-K normalizer for cover metadata and structural headings."""

    def normalize_headers(
        self, text: str, metadata: dict[str, Any] | None = None
    ) -> str:
        _ = metadata
        return normalize_headers(text, FORM_10K_GRAMMAR)


__all__ = ["Form10KNormalizer"]
