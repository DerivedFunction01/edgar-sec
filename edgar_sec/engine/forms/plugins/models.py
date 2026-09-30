"""Per-form plugin contracts for the shared normalization pipeline.

The engine is a single linear chain of pure functions. A form family does not
get its own pipeline subclass; it supplies *data* (cover checkbox schema,
boundary signal policy, structural toggles) and *hooks* (content transform,
stub/refetch evaluator) that the shared chain consults. That keeps the stage
order in exactly one place.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from edgar_sec.domain.forms.decisions import DecisionAction, EvaluatorDecision
from edgar_sec.domain.forms.schemas import CoverCheckboxSchema
from edgar_sec.engine.forms.cover.models import BoundarySignal
from edgar_sec.foundation.text.healing import PhraseSequenceRule

#: Family key used for forms with no modeled profile.
GENERIC_FAMILY = "GENERIC"

#: A per-form hook that rewrites already-normalized text. Receives and returns
#: the full document text; must be pure.
ContentTransform = Callable[[str], str]

#: A per-form hook that triages normalized text for stub/delegation content and
#: decides whether an exhibit sub-document must be fetched.
Evaluator = Callable[[str], EvaluatorDecision]


@dataclass(frozen=True, slots=True)
class FormPlugin:
    """Form-family data and hooks consumed by the shared normalization chain."""

    family: str
    cover_schema: CoverCheckboxSchema | None = None
    boundary_signals: tuple[BoundarySignal, ...] = ()
    enable_body_start: bool = True
    transform_content: ContentTransform | None = None
    evaluator: Evaluator | None = None
    healing_rules: tuple[PhraseSequenceRule, ...] = ()


__all__ = [
    "GENERIC_FAMILY",
    "ContentTransform",
    "DecisionAction",
    "Evaluator",
    "EvaluatorDecision",
    "FormPlugin",
]
