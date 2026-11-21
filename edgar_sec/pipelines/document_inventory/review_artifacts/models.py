"""Typed summary records for parser review artifact runs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ReviewSummary:
    total: int
    parsed: int
    unrecognized: int
    parse_failure: int
    replay_failure: int
    execution_error: int
    entries_total: int
    failed: int


@dataclass(frozen=True, slots=True)
class ReviewRunResult:
    review_id: str
    output_root: Path
    summary: ReviewSummary
    exit_code: int
