"""Form evaluator and normalizer protocols, decision actions, and models."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol, runtime_checkable

from defs.sec_forms.cover import CoverBoundary
from defs.sec_forms.page_markers import PageMarkerAnalysis

from ...core.schemas import DocumentLocator


class DecisionAction(str, Enum):
    """Action to take after form-level triage."""

    PROCEED = "proceed"
    REFETCH_SUB_DOC = "refetch_sub_doc"
    SKIP_HARD_STUB = "skip_hard_stub"


@dataclass(frozen=True, slots=True)
class PreprocessedDocument:
    """Intermediate representation produced by the generic preprocessor."""

    raw_text: str
    cleaned_text: str
    word_count: int
    has_html_tags: bool
    detected_encoding: str
    metadata: dict[str, Any] = field(default_factory=dict)
    page_analysis: PageMarkerAnalysis | None = None
    representation: str = "ascii"


@dataclass(frozen=True, slots=True)
class CoverPreprocessResult:
    """Cover-processed text and the boundary selected for later stages."""

    html: str
    matched: bool
    template: str | None
    confidence: float
    reason: str
    cover_boundary: CoverBoundary


@dataclass(frozen=True, slots=True)
class RefetchDecision:
    """Decision emitted by form evaluators determining next pipeline actions."""

    action: DecisionAction
    target_exhibit: str | None = None
    reason: str = ""
    is_stub: bool = False
    category: str = "standard_full"
    confidence: float = 1.0
    metadata: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class FormEvaluator(Protocol):
    """Protocol for form-family specific stub and refetch evaluators."""

    def evaluate(
        self,
        preprocessed: PreprocessedDocument,
        locator: DocumentLocator,
    ) -> RefetchDecision:
        """Evaluate preprocessed content and determine if refetching or skipping is required."""
        ...


@runtime_checkable
class FormNormalizer(Protocol):
    """Protocol for form-family specific cover and heading normalization passes."""

    def preprocess_cover(
        self,
        html_text: str,
        metadata: dict[str, Any] | None = None,
        page_analysis: PageMarkerAnalysis | None = None,
    ) -> CoverPreprocessResult:
        """Apply form-family cover preprocessing and return boundary metadata."""
        ...

    def normalize_headers(
        self,
        text: str,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Apply form-family specific section and item heading normalization."""
        ...


__all__ = [
    "CoverPreprocessResult",
    "DecisionAction",
    "FormEvaluator",
    "FormNormalizer",
    "PreprocessedDocument",
    "RefetchDecision",
]
