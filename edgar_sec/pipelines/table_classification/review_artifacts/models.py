"""Typed summary records for classification review runs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ReviewSummary:
    """Run-level counts for one classification review run."""

    total: int
    completed: int
    stale_fixture: int
    execution_error: int
    tables: int


@dataclass(frozen=True, slots=True)
class ReviewRunResult:
    """One finished review run: its id, root, summary, and exit code."""

    review_id: str
    output_root: Path
    summary: ReviewSummary
    exit_code: int
