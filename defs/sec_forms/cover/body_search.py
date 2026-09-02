"""Backward search and body confirmation for cover boundaries."""

from __future__ import annotations

from typing import Any

from defs.sec_forms.cover.models import BodyRoot
from defs.sec_forms.cover.rules import CompiledCoverRules, compile_cover_rules
from defs.sec_forms.cover.structure import (
    is_continuation_prose,
    match_structural_line,
)

_BACKWARD_SEARCH_LIMIT = 150
_BACKWARD_CONFIRM_WINDOW = 8


def _next_nonblank_line(lines: list[str], start_line: int) -> tuple[int, str] | None:
    for index in range(start_line, len(lines)):
        stripped = lines[index].strip()
        if stripped:
            return index, stripped
    return None


def _score_body_paragraph(paragraph: str, rules: CompiledCoverRules) -> float:
    """Score a paragraph for body-like content using body-only vocabulary."""
    if len(paragraph.split()) < 8:
        return 0.0
    ngram_hits = len(rules.body_ngram.findall(paragraph))
    verb_hits = len(rules.body_verb.findall(paragraph))
    if ngram_hits >= 2:
        return 0.85
    if ngram_hits >= 1 and verb_hits >= 1:
        return 0.7
    if ngram_hits >= 1 or verb_hits >= 2:
        return 0.5
    return 0.0


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
            score = _score_body_paragraph(stripped, rules)
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
