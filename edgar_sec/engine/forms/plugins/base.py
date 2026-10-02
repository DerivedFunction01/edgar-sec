"""The `FormPlugin` record and the default evaluator.

A plugin is configuration data: a frozen dataclass specifying the execution flags
and triage evaluator for a given SEC form family. `plugins/registry.py` seeds
instances per family and resolves a raw form string to its plugin; `normalize.py`
reads the stage gates during document normalization.

`evaluate_generic` is the fallback triage evaluator returned for an unmodelled
or generic form family.
"""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.domain.forms.common.decisions import DecisionAction, EvaluatorDecision
from edgar_sec.domain.forms.common.models import Evaluator

#: Family key for a form string that resolves to no modelled family.
GENERIC_FAMILY = "GENERIC"


@dataclass(frozen=True, slots=True)
class FormPlugin:
    """What the shared normalization chain does differently for one family.

    ``family`` is the canonical key the registry resolved to, not the raw input
    string: ``10-K405`` and ``10-K/A`` select the same plugin, and a consumer
    that reads the un-canonicalized form has to redo the alias resolution to get
    the identity it already had.

    ``enable_toc`` and ``enable_body_start`` gate real normalization stages — an
    annual report's table of contents is cut
    out of the text and a body root is resolved, an 8-K gets neither — so a
    plugin whose flags are wrong silently returns text with a TOC still in it.

    ``evaluator`` is the post-normalization triage hook, typed as the shared
    ``Evaluator`` alias so it is callable with the normalized text alone.
    """

    family: str
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
