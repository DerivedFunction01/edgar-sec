"""The `FormPlugin` record and the default evaluator: a plugin is the execution flags
and triage evaluator for one form family, and `evaluate_generic` is the fallback
for an unmodelled family.
"""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.domain.forms.common.decisions import DecisionAction, EvaluatorDecision
from edgar_sec.domain.forms.common.models import Evaluator

#: Family key for a form string that resolves to no modelled family.
GENERIC_FAMILY = "GENERIC"


@dataclass(frozen=True, slots=True)
class FormPlugin:
    """What the shared normalization chain does differently for one family. `family`
    is the canonical resolved key, not the raw input form.
    """

    family: str
    # Both gates control real stages, so wrong flags leave a TOC in the text.
    enable_toc: bool = False
    enable_body_start: bool = False
    evaluator: Evaluator | None = None


def evaluate_generic(text: str) -> EvaluatorDecision:
    """Triage a filing of no modelled family by proceeding with its payload."""
    _ = text
    return EvaluatorDecision(
        action=DecisionAction.PROCEED,
        target_exhibit=None,
        reason="Generic form evaluation placeholder; proceeding with primary payload.",
        is_stub=False,
        category="standard_full",
        confidence=1.0,
    )


__all__ = [
    "GENERIC_FAMILY",
    "FormPlugin",
    "evaluate_generic",
]
