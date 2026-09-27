"""Form evaluator protocols, decision actions, and generic evaluation models."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol, runtime_checkable

from defs.sec_documents.models import PreprocessedDocument


class DecisionAction(str, Enum):
    """Action to take after form-level triage."""

    PROCEED = "proceed"
    REFETCH_SUB_DOC = "refetch_sub_doc"
    SKIP_HARD_STUB = "skip_hard_stub"


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
        locator: Any = None,
    ) -> RefetchDecision:
        """Evaluate preprocessed content and determine if refetching or skipping is required."""
        ...


class GenericFormEvaluator(FormEvaluator):
    """Fallback evaluator for all generic/unspecified form types."""

    def evaluate(
        self,
        preprocessed: PreprocessedDocument,
        locator: Any = None,
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


def get_evaluator(form: str | None) -> FormEvaluator:
    """Resolve the appropriate FormEvaluator for a given form type."""
    if not form:
        return GenericFormEvaluator()
    from defs.sec_forms.families import resolve_alias

    family = resolve_alias(form)
    if family == "10-K":
        from defs.sec_forms.forms.annual.evaluator import AnnualEvaluator

        return AnnualEvaluator()
    elif family == "10-Q":
        from defs.sec_forms.forms.quarterly.evaluator import QuarterlyEvaluator

        return QuarterlyEvaluator()
    elif family == "8-K":
        from defs.sec_forms.forms.current_report.evaluator import (
            CurrentReportEvaluator,
        )

        return CurrentReportEvaluator()
    return GenericFormEvaluator()


__all__ = [
    "DecisionAction",
    "FormEvaluator",
    "GenericFormEvaluator",
    "RefetchDecision",
    "get_evaluator",
]
