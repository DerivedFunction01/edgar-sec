"""Backward search and body confirmation for cover boundaries."""

from __future__ import annotations

from typing import Any

from defs.sec_forms.cover.models import BodyRoot
from defs.sec_forms.cover.rules import CompiledCoverRules, compile_cover_rules
from defs.sec_forms.cover.structure import (
    RE_ITEM_REFERENCE,
    is_continuation_prose,
    match_structural_line,
)
from defs.sec_forms.cover.toc import (
    RE_TOC_NUMERIC_LABEL,
    looks_like_toc_row,
    looks_like_toc_tabular,
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
_MAX_PARAGRAPH_LINES = 8
_MAX_PARAGRAPH_WORDS = 160

# Backward confirmation accepts only score-2/score-3 lexical evidence;
# score-1 evidence stays ambiguous and below the acceptance gate.
_SCORE_CONFIDENCE = {0: 0.0, 1: 0.5, 2: 0.7, 3: 0.85}


def _next_nonblank_line(lines: list[str], start_line: int) -> tuple[int, str] | None:
    for index in range(start_line, len(lines)):
        stripped = lines[index].strip()
        if stripped:
            return index, stripped
    return None


def _is_toc_like_line(stripped: str) -> bool:
    """Return whether a line is tabular TOC content rather than body prose.

    Mirrors the depth-guard skips: semantic headings recur inside TOC rows
    ("Item 7. Management's Discussion and Analysis") and must not become
    backward body roots.
    """
    if looks_like_toc_row(stripped) or looks_like_toc_tabular(stripped):
        return True
    return bool(
        RE_ITEM_REFERENCE.match(stripped) or RE_TOC_NUMERIC_LABEL.match(stripped)
    )


def _containing_paragraph(lines: list[str], index: int) -> str:
    """Return the bounded paragraph containing ``index``.

    Backward line scoring under-scores multi-line body prose whose lexical
    evidence spans line wraps; scoring the containing logical paragraph gives
    the evaluator the full unit. Bounded so a runaway block cannot dominate.
    """
    first = index
    while (
        first > 0 and lines[first - 1].strip() and index - first < _MAX_PARAGRAPH_LINES
    ):
        first -= 1
    last = index
    while (
        last + 1 < len(lines)
        and lines[last + 1].strip()
        and last - first < _MAX_PARAGRAPH_LINES
    ):
        last += 1
    words = " ".join(line.strip() for line in lines[first : last + 1]).split()
    return " ".join(words[:_MAX_PARAGRAPH_WORDS])


def _gap_is_padding(lines: list[str], root_line: int, provisional_end: int) -> bool:
    """Return whether the gap between a body root and the boundary is blank tail."""
    limit = min(provisional_end, len(lines))
    non_blank = [
        lines[index].strip()
        for index in range(root_line + 1, max(root_line + 1, limit))
        if index < len(lines) and lines[index].strip()
    ]
    return len(non_blank) <= 2 and all(len(line) <= 60 for line in non_blank)


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
    in_table = False

    for index in range(start, search_start - 1, -1):
        line = lines[index]
        stripped = line.strip()
        if not stripped:
            continue
        upper = stripped.upper()
        if "<TABLE" in upper:
            in_table = True
            continue
        if "</TABLE" in upper:
            in_table = False
            continue
        if in_table or _is_toc_like_line(stripped):
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
            bow_score = _score_body_paragraph(
                _containing_paragraph(lines, index), rules.lexical
            )
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

    if gap <= _BACKWARD_CONFIRM_WINDOW or _gap_is_padding(
        lines, root.line, provisional_end
    ):
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
