"""Form 8-K family document normalizer."""

from __future__ import annotations

from typing import Any

from ..base import FormNormalizer
from ..shared.headers import FORM_8K_GRAMMAR, normalize_headers


class Form8KNormalizer(FormNormalizer):
    """Form 8-K normalizer for current-report Section/Item headings."""

    def normalize_headers(
        self, text: str, metadata: dict[str, Any] | None = None
    ) -> str:
        _ = metadata
        return normalize_headers(text, FORM_8K_GRAMMAR)


__all__ = ["Form8KNormalizer"]
