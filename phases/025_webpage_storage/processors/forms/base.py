"""Form evaluator protocols, decision actions, and refetch decision models."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol, runtime_checkable

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
