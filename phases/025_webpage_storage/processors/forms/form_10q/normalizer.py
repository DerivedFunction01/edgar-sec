"""Form 10-Q family document normalizer."""

from __future__ import annotations

from typing import Any

from ..base import FormNormalizer


class Form10QNormalizer(FormNormalizer):
    """Form 10-Q normalizer."""

    def normalize(self, text: str, metadata: dict[str, Any] | None = None) -> str:
        _ = metadata
        return text


__all__ = ["Form10QNormalizer"]
