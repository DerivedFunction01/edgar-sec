"""TOC span data models."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TocEvidence:
    """Named evidence supporting a TOC span."""

    name: str
    line: int | None = None
    details: str = ""


@dataclass(frozen=True, slots=True)
class TocSpan:
    """An exclusive source span containing a detected table of contents."""

    start_line: int
    end_line: int
    start_offset: int
    end_offset: int
    method: str
    confidence: float
    evidence: tuple[TocEvidence, ...] = ()
    approximate: bool = False


__all__ = ["TocEvidence", "TocSpan"]
