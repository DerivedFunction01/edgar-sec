"""Form evaluator decisions and actions."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class DecisionAction(StrEnum):
    """Action to take after form-level structural triage."""

    PROCEED = "proceed"
    REFETCH_SUB_DOC = "refetch_sub_doc"
    SKIP_HARD_STUB = "skip_hard_stub"


@dataclass(frozen=True, slots=True)
class EvaluatorDecision:
    """Decision emitted by form evaluators determining next pipeline actions."""

    action: DecisionAction
    target_exhibit: str | None = None
    reason: str = ""
    is_stub: bool = False
    category: str = "standard_full"
    confidence: float = 1.0
    metadata: dict[str, Any] = field(default_factory=dict)


__all__ = [
    "DecisionAction",
    "EvaluatorDecision",
]
