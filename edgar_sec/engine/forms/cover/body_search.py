"""Backward body search and cover-boundary confirmation.

A forward signal proposes where the cover ends. This module checks that
proposal from the other direction: scanning *backwards* from the proposed end
for the first line that is unambiguously body prose. If that line is far from
the proposal, the proposal overshot and is pulled back to it; if it is close,
the proposal is confirmed and the evidence records that confirmation.

Owning both directions is what keeps the boundary honest. A forward-only
detector will happily end a 10-K cover at the first ``PART I`` it meets, which
for a filing with a long exhibit index is deep inside the body.
"""

from __future__ import annotations

import re

from edgar_sec.engine.forms.cover.body_evidence import (
    is_body_prose,
    score_body_text,
    score_confidence,
)
from edgar_sec.engine.forms.cover.models import BoundaryEvidence
from edgar_sec.engine.forms.cover.structure import (
    RE_ITEM_REFERENCE,
    RE_PART_REFERENCE,
    is_continuation_prose,
    match_structural_line,
)
from edgar_sec.foundation.text.patterns import RE_DOT_LEADER, RE_PAGE_NUMBER_SUFFIX

_BACKWARD_SEARCH_LIMIT = 150
_BACKWARD_CONFIRM_WINDOW = 8
_MAX_PARAGRAPH_LINES = 8
_MAX_PARAGRAPH_WORDS = 160

# A leading numeric label as TOC rows render it ("1. Business ....... 1").
RE_TOC_NUMERIC_LABEL = re.compile(r"^\s*\d{1,2}[.)]\s+\S")


def is_toc_layout_line(stripped: str) -> bool:
    """Return whether a line is *rendered* TOC layout, safe for heading tests.

    This is the strict test, and it must not reject a structural heading. Two
    facts drive it:

    * ``RE_PAGE_NUMBER_SUFFIX`` also matches a trailing Roman numeral, so a bare
      ``PART I`` satisfies it. Table-cell TOC detection tolerates that because a
      lone ``PART I`` cell really is a TOC row, but at line scope it is a
      heading.
    * A TOC row always pairs the section reference with a title tail and a page
      reference; a heading has neither.

    So a line is TOC layout when it carries a dot leader with a page suffix, or
    when what remains after removing the section reference and the page suffix is
    still a multi-word title.
    """
    if not stripped:
        return False
    has_page = bool(RE_PAGE_NUMBER_SUFFIX.search(stripped))
    if RE_DOT_LEADER.search(stripped) and has_page:
        return True
    if not has_page:
        return False
    core = RE_PART_REFERENCE.sub(" ", RE_ITEM_REFERENCE.sub(" ", stripped))
    core = RE_PAGE_NUMBER_SUFFIX.sub(" ", core).strip(" .:;\t")
    return len(core.split()) >= 2


def is_toc_like_line(stripped: str) -> bool:
    """Return whether a line is tabular TOC content rather than body prose.

    Broader than :func:`is_toc_layout_line`: it also matches a bare section
    reference, because semantic headings recur inside TOC rows
    ("Item 7. Management's Discussion and Analysis") and must not become
    backward body roots. Never use it to reject a structural heading candidate.
    """
    if is_toc_layout_line(stripped):
        return True
    return bool(
        RE_ITEM_REFERENCE.match(stripped) or RE_TOC_NUMERIC_LABEL.match(stripped)
    )


def containing_paragraph(lines: list[str], index: int) -> str:
    """Return the bounded paragraph containing ``index``.

    Line-level scoring under-scores wrapped body prose whose lexical evidence
    spans a line break; scoring the containing logical paragraph gives the
    evaluator the full unit. Bounded so a runaway block cannot dominate.
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


def _next_nonblank_line(lines: list[str], start_line: int) -> tuple[int, str] | None:
    for index in range(start_line, len(lines)):
        stripped = lines[index].strip()
        if stripped:
            return index, stripped
    return None


def find_body_root_backward(
    lines: list[str],
    provisional_end: int,
    cover_start_line: int | None = None,
) -> tuple[int, str, float] | None:
    """Scan backward from ``provisional_end`` for the first reliable body root.

    Returns ``(line, root_type, confidence)``. Structural headings win outright
    because they are unambiguous; otherwise the nearest semantic or substantive
    prose root is used.
    """
    if provisional_end <= 0:
        return None
    search_start = max(
        0,
        provisional_end - _BACKWARD_SEARCH_LIMIT,
        cover_start_line if cover_start_line is not None else 0,
    )
    start = min(provisional_end, len(lines) - 1)
    first_semantic: tuple[int, str, float] | None = None
    first_substantive: tuple[int, str, float] | None = None
    in_table = False

    for index in range(start, search_start - 1, -1):
        stripped = lines[index].strip()
        if not stripped:
            continue
        upper = stripped.upper()
        if "<TABLE" in upper:
            in_table = True
            continue
        if "</TABLE" in upper:
            in_table = False
            continue
        if in_table or is_toc_like_line(stripped):
            continue
        match = match_structural_line(stripped, index)
        if match is not None and match.is_exact_heading:
            following = _next_nonblank_line(lines, index + 1)
            if following is not None and is_continuation_prose(following[1]):
                continue
            if match.role == "part":
                return index, "structural", 0.95
            if match.role == "item":
                return index, "structural", 0.9
        if first_semantic is None and is_body_prose(stripped):
            first_semantic = (index, "semantic", 0.7)
            continue
        if first_substantive is None:
            score = score_body_text(containing_paragraph(lines, index))
            confidence = score_confidence(score)
            if confidence >= 0.7:
                first_substantive = (index, "substantive", confidence)

    return first_semantic if first_semantic is not None else first_substantive


def _gap_is_padding(lines: list[str], root_line: int, provisional_end: int) -> bool:
    """Return whether the gap between a body root and the boundary is blank tail."""
    limit = min(provisional_end, len(lines))
    non_blank = [
        lines[index].strip()
        for index in range(root_line + 1, max(root_line + 1, limit))
        if index < len(lines) and lines[index].strip()
    ]
    return len(non_blank) <= 2 and all(len(line) <= 60 for line in non_blank)


def confirm_backward_body(
    lines: list[str],
    provisional_end: int,
    cover_start_line: int | None,
    evidence: list[BoundaryEvidence],
) -> tuple[int, list[BoundaryEvidence]]:
    """Confirm or adjust a provisional forward boundary using backward search."""
    root = find_body_root_backward(lines, provisional_end, cover_start_line)
    if root is None:
        return provisional_end, evidence
    root_line, root_type, confidence = root
    gap = provisional_end - root_line

    if gap <= _BACKWARD_CONFIRM_WINDOW or _gap_is_padding(
        lines, root_line, provisional_end
    ):
        evidence.append(
            BoundaryEvidence(
                name="backward_body_confirm",
                strength=confidence,
                line=root_line,
                details=(
                    f"{root_type} body root confirms forward boundary (gap={gap})"
                ),
            )
        )
        return provisional_end, evidence

    evidence.append(
        BoundaryEvidence(
            name="backward_body_adjust",
            strength=confidence,
            line=root_line,
            details=f"{root_type} body root adjusts forward boundary (gap={gap})",
        )
    )
    return root_line, evidence


__all__ = [
    "RE_TOC_NUMERIC_LABEL",
    "confirm_backward_body",
    "containing_paragraph",
    "find_body_root_backward",
    "is_toc_layout_line",
    "is_toc_like_line",
]
