"""Minimal FormPlugin model and registry for pipeline execution."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from edgar_sec.domain.forms.decisions import EvaluatorDecision


@dataclass(frozen=True, slots=True)
class FormPlugin:
    """Plugin definition for a form family."""

    form: str
    evaluator: Callable[[str], EvaluatorDecision | None] | None = None


def get_plugin(form: str | None) -> FormPlugin:
    """Resolve plugin for given form type."""
    return FormPlugin(form=form or "UNKNOWN", evaluator=None)


__all__ = [
    "FormPlugin",
    "get_plugin",
]
