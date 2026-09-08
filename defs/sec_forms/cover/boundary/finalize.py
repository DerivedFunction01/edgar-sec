"""Boundary finalization helpers."""

from __future__ import annotations

from defs.sec_forms.cover.body_search import _confirm_backward_body
from defs.sec_forms.cover.models import (
    BoundaryEvidence,
    BoundaryMethod,
    CoverBoundary,
    CoverStart,
)
from defs.sec_forms.cover.rules import compile_cover_rules

from .helpers import _line_offset


def _unknown(method: BoundaryMethod = BoundaryMethod.UNKNOWN) -> CoverBoundary:
    return CoverBoundary(
        end_line=None,
        end_offset=None,
        method=method,
        confidence=0.0,
        evidence=(),
        approximate=True,
    )


def _finalize_boundary(
    end_line: int,
    method: BoundaryMethod,
    confidence: float,
    evidence: list[BoundaryEvidence],
    cover_start: CoverStart,
    lines: list[str],
    continued_cover: bool = False,
    confirm_backward: bool = True,
    rules: object | None = None,
) -> CoverBoundary:
    """Run backward body confirmation and build the final boundary."""
    if confirm_backward:
        rules = rules or compile_cover_rules()
        adjusted_end, adjusted_evidence = _confirm_backward_body(
            lines, end_line, cover_start.start_line, evidence, rules
        )
    else:
        adjusted_end, adjusted_evidence = end_line, evidence
    return CoverBoundary(
        end_line=adjusted_end,
        end_offset=_line_offset(lines, adjusted_end),
        method=method,
        confidence=confidence,
        evidence=tuple(adjusted_evidence),
        start_line=cover_start.start_line,
        start_offset=cover_start.start_offset,
        start_evidence=cover_start.evidence,
        approximate=True,
        continued_cover=continued_cover,
    )
