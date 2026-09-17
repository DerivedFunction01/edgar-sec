"""Form 8-K family document normalizer."""

from __future__ import annotations

from typing import Any

from ..base import FormNormalizer


class Form8KNormalizer(FormNormalizer):
    """Form 8-K normalizer."""

    def normalize(self, text: str, metadata: dict[str, Any] | None = None) -> str:
        _ = metadata
        return text


__all__ = ["Form8KNormalizer"]
