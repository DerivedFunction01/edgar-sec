"""Base types and dataclasses for condition-aware grid repairs and templates."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

SpanGroup = tuple[int, int, int, str]
TemplateMatcher = Callable[[list[list[str]], int, list[SpanGroup]], list[SpanGroup]]
TemplateApplier = Callable[[list[list[str]], int, set[int], list[SpanGroup]], None]
GridRepair = Callable[[list[list[str]], int, set[int]], None]


@dataclass(frozen=True)
class GridTemplate:
    """A registered grid repair template with match condition and apply action."""

    name: str
    match: TemplateMatcher
    apply: TemplateApplier


__all__ = [
    "GridRepair",
    "GridTemplate",
    "SpanGroup",
    "TemplateApplier",
    "TemplateMatcher",
]
