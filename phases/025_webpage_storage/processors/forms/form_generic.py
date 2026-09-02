"""Generic fallback form evaluator and normalizer.

This module provides the fallback evaluator and normalizer for all unspecified form types
(Form 20-F, 11-K, 6-K, Form 3/4/5, Form 144, SC 13D/G, etc.).
"""

from __future__ import annotations

from typing import Any

from defs.sec_forms.cover import BoundaryInput, find_cover_boundary

from ...core.schemas import DocumentLocator
from .base import (
    CoverPreprocessResult,
    DecisionAction,
    FormEvaluator,
    FormNormalizer,
    PreprocessedDocument,
    RefetchDecision,
)


class GenericFormEvaluator(FormEvaluator):
    """Fallback evaluator for all generic/unspecified form types."""

    def evaluate(
        self,
        preprocessed: PreprocessedDocument,
        locator: DocumentLocator,
    ) -> RefetchDecision:
        """Evaluate a generic filing document."""
        _ = locator
        _ = preprocessed
        return RefetchDecision(
            action=DecisionAction.PROCEED,
            target_exhibit=None,
            reason="Generic form evaluation placeholder; proceeding with primary payload.",
            is_stub=False,
            category="standard_full",
            confidence=1.0,
        )


class GenericFormNormalizer(FormNormalizer):
    """Fallback normalizer for generic/unspecified form types."""

    def preprocess_cover(
        self,
        html_text: str,
        metadata: dict[str, Any] | None = None,
    ) -> CoverPreprocessResult:
        _ = metadata
        boundary = find_cover_boundary(BoundaryInput(html_text), None)
        return CoverPreprocessResult(
            html=html_text,
            matched=False,
            template=None,
            confidence=0.0,
            reason="no_cover_profile_or_evidence",
            cover_boundary=boundary,
        )

    def normalize_headers(
        self,
        text: str,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        _ = metadata
        return text


__all__ = ["GenericFormEvaluator", "GenericFormNormalizer"]
