from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ReviewSummary:
    total: int
    completed: int
    replay_failure: int
    execution_error: int


@dataclass(frozen=True, slots=True)
class ReviewRunResult:
    review_id: str
    output_root: Path
    summary: ReviewSummary
    exit_code: int


@dataclass(frozen=True, slots=True)
class ProcessingReviewArtifact:
    artifact_sha256: str
    path: Path
