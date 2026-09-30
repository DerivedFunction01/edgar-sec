"""Page marker actions and types required by document storage pipelines."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class PageMarkerAction(StrEnum):
    """Actions applied to detected page markers."""

    REMOVE = "remove"
    PRESERVE = "preserve"


@dataclass(frozen=True, slots=True)
class PageMarkerDecision:
    """Action recorded for a candidate page marker."""

    action: PageMarkerAction
    marker: Any = None


@dataclass(frozen=True, slots=True)
class PageMarkerAnalysis:
    """Summary of page marker detection across a document."""

    markers: list[Any] = field(default_factory=list)
    decisions: list[PageMarkerDecision] = field(default_factory=list)


__all__ = [
    "PageMarkerAction",
    "PageMarkerAnalysis",
    "PageMarkerDecision",
]
