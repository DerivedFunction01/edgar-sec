"""Backward search and body confirmation for cover boundaries."""

from __future__ import annotations

from typing import Any

from defs.sec_forms.cover.models import BodyRoot
from defs.sec_forms.cover.rules import CompiledCoverRules, compile_cover_rules
from defs.sec_forms.cover.structure import (
    is_continuation_prose,
    match_structural_line,
)
from defs.text.bow import (
    BowScore,
    CompiledEvidencePack,
    EvidenceContext,
    score_tokens,
    tokenize,
)

_BACKWARD_SEARCH_LIMIT = 150
_BACKWARD_CONFIRM_WINDOW = 8

# Backward confirmation accepts only score-2/score-3 lexical evidence;
# score-1 evidence stays ambiguous and below the acceptance gate.
_SCORE_CONFIDENCE = {0: 0.0, 1: 0.5, 2: 0.7, 3: 0.85}


def _next_nonblank_line(lines: list[str], start_line: int) -> tuple[int, str] | None:
    for index in range(start_line, len(lines)):
        stripped = lines[index].strip()
        if stripped:
            return index, stripped
    return None


def _score_body_paragraph(paragraph: str, lexical: CompiledEvidencePack) -> BowScore:
    """Score one backward-search line with the shared lexical evaluator."""
    return score_tokens(
        tokenize(paragraph),
        lexical,
        EvidenceContext(unit_kind="line"),
    )


def _find_body_root_backward(
    lines: list[str],
    provisional_end: int,
    cover_start_line: int | None,
    rules: CompiledCoverRules | None = None,
) -> BodyRoot | None:
    """Scan backward from ``provisional_end`` to find the first reliable body root."""
    if provisional_end <= 0:
        return None
    rules = rules or compile_cover_rules()
    search_start = max(
        0,
        provisional_end - _BACKWARD_SEARCH_LIMIT,
        cover_start_line if cover_start_line is not None else 0,
    )
    start = min(provisional_end, len(lines) - 1)
    first_semantic: BodyRoot | None = None
    first_substantive: BodyRoot | None = None

    for index in range(start, search_start - 1, -1):
        line = lines[index]
        stripped = line.strip()
        if not stripped:
            continue
        match = match_structural_line(stripped, index)
        if match is not None and match.is_exact_heading:
            following = _next_nonblank_line(lines, index + 1)
            if following is not None and is_continuation_prose(following[1]):
                continue
            if match.role == "part":
                return BodyRoot(
                    line=index,
                    root_type="structural",
                    confidence=0.95,
                    label=stripped,
                )
            if match.role == "item":
                return BodyRoot(
                    line=index,
                    root_type="structural",
                    confidence=0.9,
                    label=stripped,
                )
        if first_semantic is None and rules.body_semantic.search(stripped):
            first_semantic = BodyRoot(
                line=index,
                root_type="semantic",
                confidence=0.7,
                label=stripped,
            )
            continue
        if first_substantive is None:
            bow_score = _score_body_paragraph(stripped, rules.lexical)
            score = _SCORE_CONFIDENCE.get(bow_score.score, 0.0)
            if score >= 0.7:
                first_substantive = BodyRoot(
                    line=index,
                    root_type="substantive",
                    confidence=score,
                    label=stripped[:80],
                )

    if first_semantic is not None:
        return first_semantic
    return first_substantive


def confirm_backward_body(
    lines: list[str],
    provisional_end: int,
    cover_start_line: int | None,
    evidence: list[Any],
    rules: CompiledCoverRules | None = None,
) -> tuple[int, list[Any]]:
    """Confirm or adjust a provisional forward boundary using backward search."""
    from defs.sec_forms.cover.boundary import BoundaryEvidence

    rules = rules or compile_cover_rules()
    root = _find_body_root_backward(lines, provisional_end, cover_start_line, rules)
    if root is None:
        return provisional_end, evidence

    gap = provisional_end - root.line

    if gap <= _BACKWARD_CONFIRM_WINDOW:
        evidence.append(
            BoundaryEvidence(
                name="backward_body_confirm",
                strength=root.confidence,
                line=root.line,
                details=(
                    f"{root.root_type} body root confirms forward boundary (gap={gap})"
                ),
            )
        )
        return provisional_end, evidence

    evidence.append(
        BoundaryEvidence(
            name="backward_body_adjust",
            strength=root.confidence,
            line=root.line,
            details=(
                f"{root.root_type} body root adjusts forward boundary (gap={gap})"
            ),
        )
    )
    return root.line, evidence


__all__ = [
    "BodyRoot",
    "_confirm_backward_body",
    "_find_body_root_backward",
    "_next_nonblank_line",
    "_score_body_paragraph",
    "confirm_backward_body",
]

_confirm_backward_body = confirm_backward_body
