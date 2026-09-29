"""Forward body-start detection after the cover boundary.

Resolves the first sufficiently validated body region. The detector prefers a
later validated start over an early false start: a late start may leave some
ordinary prose hard-wrapped, while an early start can corrupt a table, list,
signature, or cover layout.

Two candidate kinds are scanned forward from the cover end:

``structural``
    An isolated PART/ITEM heading, validated against TOC context, table/list
    context, multi-reference headings, and adjacent continuation prose.
``semantic``
    A substantive discussion section ("Risk Factors", "Management's Discussion
    and Analysis") whose text carries body-lexical evidence.

A candidate is only accepted when substantive prose follows it, so a heading
that introduces nothing but a table or a blank run is rejected.

Departure from v1
-----------------
v1 also had a document-level ``classify_units`` pass (``defs/text/structure/
logical_units.py``) that segmented text into paragraph/table/list/signature
units. v2 has no unit classifier, so unit-kind context is approximated by the
line-level structural and lexical gates that already encode the same
distinctions (TOC-like rows, tagged tables, exact headings).
"""

from __future__ import annotations

from edgar_sec.engine.forms.cover.body_evidence import (
    MIN_BODY_SCORE,
    is_semantic_heading,
    score_body_text,
)
from edgar_sec.engine.forms.cover.body_search import is_toc_layout_line
from edgar_sec.engine.forms.cover.models import (
    BodyAnchorType,
    BodyStart,
    BodyStartEvidence,
)
from edgar_sec.engine.forms.cover.structure import (
    is_continuation_prose,
    is_preceding_continuation,
    match_structural_line,
)

# Bounded forward search window after the cover end.
_BODY_START_SEARCH_WINDOW = 300
# Maximum lines a structural heading can precede its first prose unit.
_HEADING_PROSE_WINDOW = 25
# Minimum words a candidate paragraph needs before it is scored at all.
_MIN_PARAGRAPH_WORDS = 8


def _next_nonblank_line(lines: list[str], start: int) -> tuple[int, str] | None:
    return next(
        ((i, s) for i in range(start, len(lines)) if (s := lines[i].strip())),
        None,
    )


def _prev_nonblank_line(lines: list[str], start: int) -> tuple[int, str] | None:
    return next(
        ((i, s) for i in range(start, -1, -1) if (s := lines[i].strip())),
        None,
    )


def _validate_structural_heading(
    lines: list[str], heading_line: int
) -> tuple[bool, str]:
    """Validate a structural PART/ITEM heading as a body anchor."""
    stripped = lines[heading_line].strip()
    if is_toc_layout_line(stripped):
        return False, "heading in TOC context"

    match = match_structural_line(stripped, heading_line)
    if match is None or not match.is_exact_heading:
        return False, "not an exact structural heading"
    if match.reference_count > 1:
        return False, "multiple PART/ITEM references"

    if heading_line > 0:
        prev = _prev_nonblank_line(lines, heading_line - 1)
        if prev is not None and is_preceding_continuation(prev[1]):
            return False, "preceded by continuation token"

    following = _next_nonblank_line(lines, heading_line + 1)
    if following is not None and is_continuation_prose(following[1]):
        return False, "followed by lowercase continuation prose"

    return True, "valid structural heading"


def _find_first_substantive_prose(
    lines: list[str], start_line: int, limit_line: int
) -> tuple[int | None, int | None]:
    """Find the first prose line at or after ``start_line`` that clears the gate.

    Consecutive short lines are merged into a bounded paragraph before scoring
    so fragmented HTML prose (split spans, short lead sentences) can still
    reach the lexical gate.
    """
    buffer: list[str] = []
    buffer_start: int | None = None
    for index in range(max(0, start_line), min(limit_line, len(lines))):
        stripped = lines[index].strip()
        if not stripped or is_toc_layout_line(stripped) or "<TABLE" in stripped.upper():
            if buffer and buffer_start is not None:
                paragraph = " ".join(buffer)
                if score_body_text(paragraph) >= MIN_BODY_SCORE:
                    return buffer_start, score_body_text(paragraph)
            buffer = []
            buffer_start = None
            continue
        if not buffer:
            buffer_start = index
        buffer.append(stripped)
        if len(" ".join(buffer).split()) < _MIN_PARAGRAPH_WORDS:
            continue
        paragraph = " ".join(buffer)
        score = score_body_text(paragraph)
        if score >= MIN_BODY_SCORE:
            return buffer_start, score
        if len(" ".join(buffer).split()) >= 160:
            buffer = []
            buffer_start = None
    return None, None


def _build_body_start(
    line: int | None,
    heading_line: int | None,
    first_unit_line: int | None,
    anchor_type: str,
    confidence: float,
    evidence_log: list[BodyStartEvidence],
    rejection_reasons: list[str],
    reason: str,
) -> BodyStart:
    return BodyStart(
        line=line,
        heading_line=heading_line,
        first_unit_line=first_unit_line,
        anchor_type=anchor_type,
        confidence=confidence,
        evidence=tuple(evidence_log),
        delayed=len(rejection_reasons) > 0,
        rejection_reasons=tuple(rejection_reasons),
        reason=reason,
    )


def _unknown_body_start(reason: str) -> BodyStart:
    return _build_body_start(
        None, None, None, BodyAnchorType.UNKNOWN.value, 0.0, [], [], reason
    )


def _scan_structural_candidates(
    lines: list[str], lower_bound: int, search_limit: int
) -> list[tuple[int, str]]:
    candidates: list[tuple[int, str]] = []
    for index in range(lower_bound, search_limit):
        line = lines[index].strip()
        if not line or is_toc_layout_line(line):
            continue
        match = match_structural_line(line, index)
        if match is None or not match.is_exact_heading:
            continue
        candidates.append((index, match.label.strip()))
    return candidates


def _scan_semantic_candidates(
    lines: list[str], lower_bound: int, search_limit: int
) -> list[int]:
    return [
        index
        for index in range(lower_bound, search_limit)
        if is_semantic_heading(lines[index])
        and not is_toc_layout_line(lines[index].strip())
    ]


def find_body_start(
    text: str,
    *,
    cover_end: int | None,
    evidence: tuple = (),
    search_window: int = _BODY_START_SEARCH_WINDOW,
) -> BodyStart:
    """Find the first validated body region after cover material.

    Args:
        text: full source text, on the same frame as ``cover_end``.
        cover_end: exclusive cover boundary line.
        evidence: the form's declared boundary signals; retained so a caller
            can narrow the search without changing this signature.
        search_window: bounded forward search window.
    """
    _ = evidence
    lines = text.splitlines()
    if not lines:
        return _unknown_body_start("empty document")

    lower_bound = max(cover_end or 0, 0)
    search_limit = min(len(lines), lower_bound + search_window)

    evidence_log: list[BodyStartEvidence] = []
    rejection_reasons: list[str] = []

    candidates: list[tuple[int, str, str]] = [
        (line, "structural", label)
        for line, label in _scan_structural_candidates(lines, lower_bound, search_limit)
    ]
    candidates.extend(
        (line, "semantic", lines[line].strip())
        for line in _scan_semantic_candidates(lines, lower_bound, search_limit)
    )
    candidates.sort(key=lambda candidate: candidate[0])

    for candidate_line, kind, payload in candidates:
        if kind == "structural":
            valid, reason = _validate_structural_heading(lines, candidate_line)
            if not valid:
                rejection_reasons.append(
                    f"line {candidate_line} {payload} rejected: {reason}"
                )
                evidence_log.append(
                    BodyStartEvidence(
                        name="structural_candidate_rejected",
                        strength=0.3,
                        line=candidate_line,
                        details=f"{payload}: {reason}",
                    )
                )
                continue
            prose_limit = min(search_limit, candidate_line + _HEADING_PROSE_WINDOW)
            prose_line, score = _find_first_substantive_prose(
                lines, candidate_line + 1, prose_limit
            )
            if prose_line is not None and score is not None:
                evidence_log.append(
                    BodyStartEvidence(
                        name="structural_body_anchor",
                        strength=0.9,
                        line=candidate_line,
                        details=(
                            f"{payload} with substantive prose at line "
                            f"{prose_line} (body score {score})"
                        ),
                    )
                )
                return _build_body_start(
                    candidate_line,
                    candidate_line,
                    prose_line,
                    BodyAnchorType.STRUCTURAL.value,
                    0.9,
                    evidence_log,
                    rejection_reasons,
                    f"{payload} heading with validated prose at line {prose_line}",
                )
            rejection_reasons.append(
                f"line {candidate_line} {payload}: no substantive prose within window"
            )
        else:
            prose_limit = min(search_limit, candidate_line + _HEADING_PROSE_WINDOW)
            prose_line, score = _find_first_substantive_prose(
                lines, candidate_line + 1, prose_limit
            )
            if prose_line is None or score is None:
                rejection_reasons.append(
                    f"line {candidate_line} semantic heading: no substantive prose "
                    "within window"
                )
                continue
            evidence_log.append(
                BodyStartEvidence(
                    name="semantic_body_anchor",
                    strength=0.8,
                    line=candidate_line,
                    details=(
                        f"semantic section with substantive prose at line "
                        f"{prose_line} (body score {score})"
                    ),
                )
            )
            return _build_body_start(
                candidate_line,
                candidate_line,
                prose_line,
                BodyAnchorType.SEMANTIC.value,
                0.8,
                evidence_log,
                rejection_reasons,
                (f"semantic body section with validated prose at line {prose_line}"),
            )

    prose_line, score = _find_first_substantive_prose(lines, lower_bound, search_limit)
    if prose_line is not None and score is not None:
        evidence_log.append(
            BodyStartEvidence(
                name="substantive_body_anchor",
                strength=0.6,
                line=prose_line,
                details=(
                    "substantive prose cluster without structural heading "
                    f"(body score {score})"
                ),
            )
        )
        return _build_body_start(
            prose_line,
            None,
            prose_line,
            BodyAnchorType.SUBSTANTIVE.value,
            0.6,
            evidence_log,
            rejection_reasons,
            "substantive body prose cluster without structural heading",
        )

    return _build_body_start(
        None,
        None,
        None,
        BodyAnchorType.UNKNOWN.value,
        0.0,
        evidence_log,
        rejection_reasons,
        "no reliable body candidate within search window",
    )


__all__ = ["BodyStart", "BodyStartEvidence", "find_body_start"]
