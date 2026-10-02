"""Search corridor around the cover boundary.

The corridor is the pair of searches that bracket the boundary: a forward scan
for the opening cover cluster (:func:`find_cover_start`) and a backward scan
for the first reliable body anchor (:func:`confirm_backward_body`). Between them
sit the line helpers both directions share, the body-prose forward scan, and the
finalizer that turns a provisional end line plus its evidence rows into a
:class:`~edgar_sec.engine.forms.cover.models.CoverBoundary`.
"""

from __future__ import annotations

from typing import Any

from edgar_sec.engine.forms.cover.models import (
    BoundaryEvidence,
    BoundaryInput,
    BoundaryMethod,
    BoundarySignal,
    CoverBoundary,
    CoverBoundaryPolicy,
    CoverStart,
)
from edgar_sec.engine.forms.cover.rules import CompiledCoverRules, compile_cover_rules
from edgar_sec.engine.forms.cover.structure import (
    RE_ITEM_REFERENCE,
    is_continuation_prose,
    match_structural_line,
)
from edgar_sec.engine.forms.cover.toc.patterns import RE_TOC_NUMERIC_LABEL
from edgar_sec.engine.tables.protection.tags import (
    TAGGED_TABLE_CLOSE_RE,
    TAGGED_TABLE_OPEN_RE,
)
from edgar_sec.engine.tables.toc.patterns import (
    looks_like_toc_row,
    looks_like_toc_tabular,
)
from edgar_sec.foundation.text.evidence import (
    BowScore,
    CompiledEvidencePack,
    EvidenceContext,
    score_tokens,
    tokenize,
)

_RE_TAGGED_TABLE_OPEN = TAGGED_TABLE_OPEN_RE
_RE_TAGGED_TABLE_CLOSE = TAGGED_TABLE_CLOSE_RE

_BACKWARD_SEARCH_LIMIT = 150
_BACKWARD_CONFIRM_WINDOW = 8
_MAX_PARAGRAPH_LINES = 8
_MAX_PARAGRAPH_WORDS = 160

# Backward confirmation accepts only score-2/score-3 lexical evidence;
# score-1 evidence stays ambiguous and below the acceptance gate.
_SCORE_CONFIDENCE = {0: 0.0, 1: 0.5, 2: 0.7, 3: 0.85}

_COVER_START_SEARCH_WINDOW = 60
_COVER_START_CLUSTER_GAP = 5


def prev_nonblank_line(lines: list[str], start_line: int) -> tuple[int, str] | None:
    """Return the last non-blank line at or before ``start_line``."""
    for index in range(start_line, -1, -1):
        stripped = lines[index].strip()
        if stripped:
            return index, stripped
    return None


def next_nonblank_line(lines: list[str], start_line: int) -> tuple[int, str] | None:
    """Return the first non-blank line at or after ``start_line``."""
    for index in range(start_line, len(lines)):
        stripped = lines[index].strip()
        if stripped:
            return index, stripped
    return None


def is_toc_like_line(stripped: str) -> bool:
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


def is_proxy_reference_disclosure(line: str) -> bool:
    """Return whether a line describes another section rather than the cover."""
    stripped = line.strip().lower()
    return bool(
        stripped.startswith(
            (
                "portions of",
                "the information required",
                "information required",
                "see part",
                "refer to",
            )
        )
        or "indicate by check mark" in stripped
        or "pursuant to item 405" in stripped
        or "delinquent filers" in stripped
    )


def enabled(policy: object, signal: object) -> bool:
    """Return whether a profile policy enables one boundary signal."""
    return signal in policy.signals


def line_offset(lines: list[str], line: int) -> int:
    """Return the character offset at which ``line`` begins."""
    return sum(len(value) + 1 for value in lines[:line])


def line_at_offset(text: str, offset: int) -> int:
    """Return the line index containing ``offset``."""
    return text.count("\n", 0, offset)


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


def _scan_cover_start_cluster(
    lines: list[str],
    *,
    enabled: bool,
    rules: CompiledCoverRules,
) -> CoverStart | None:
    """Find a connected cover-shaped cluster in the opening window.

    The cluster requires at least one generic identity signal plus one
    cover-shape signal within a bounded window. The start is the first line
    of the connected cluster, not the first matched label.
    """
    if not enabled:
        return None

    evidence: list[BoundaryEvidence] = []
    first_identity: int | None = None
    first_shape: int | None = None
    cluster_start = None
    last_signal = -_COVER_START_CLUSTER_GAP - 1

    for index, line in enumerate(lines[:_COVER_START_SEARCH_WINDOW]):
        is_identity = bool(rules.cover_start_identity.search(line))
        is_shape = bool(rules.cover_start_shape.search(line))
        if not (is_identity or is_shape):
            continue
        if index - last_signal > _COVER_START_CLUSTER_GAP:
            if (
                cluster_start is not None
                and first_identity is not None
                and first_shape is not None
            ):
                return CoverStart(
                    start_line=cluster_start,
                    start_offset=line_offset(lines, cluster_start),
                    evidence=tuple(evidence),
                )
            cluster_start = index
            evidence = []
            first_identity = None
            first_shape = None
        last_signal = index
        if is_identity and first_identity is None:
            first_identity = index
            evidence.append(
                BoundaryEvidence(
                    name="cover_start_identity",
                    strength=0.95,
                    line=index,
                    details="generic cover identity signal",
                )
            )
        if is_shape and first_shape is None:
            first_shape = index
            evidence.append(
                BoundaryEvidence(
                    name="cover_start_shape",
                    strength=0.85,
                    line=index,
                    details="cover-shape field signal",
                )
            )

    if (
        cluster_start is not None
        and first_identity is not None
        and first_shape is not None
    ):
        return CoverStart(
            start_line=cluster_start,
            start_offset=line_offset(lines, cluster_start),
            evidence=tuple(evidence),
        )
    return None


def find_cover_start(
    boundary_input: BoundaryInput | str,
    policy: CoverBoundaryPolicy | None,
    *,
    cover_evidence: object | None = None,
    body_evidence: object | None = None,
) -> CoverStart:
    """Find the inclusive start of a cover-shaped cluster.

    Returns a ``CoverStart`` with ``start_line`` set to the first line of the
    connected cover-shaped cluster. Requires the ``COVER_IDENTITY_AND_LAYOUT``
    signal to be enabled; otherwise returns an unknown start.
    """
    if policy is None:
        return CoverStart(start_line=None, start_offset=None)

    rules = compile_cover_rules(cover_evidence, body_evidence)

    text = boundary_input if isinstance(boundary_input, str) else boundary_input.text
    lines = text.splitlines()
    if not lines:
        return CoverStart(start_line=None, start_offset=None)

    result = _scan_cover_start_cluster(
        lines,
        enabled=BoundarySignal.COVER_IDENTITY_AND_LAYOUT in policy.signals,
        rules=rules,
    )
    return (
        result if result is not None else CoverStart(start_line=None, start_offset=None)
    )


def _find_body_root_backward(
    lines: list[str],
    provisional_end: int,
    cover_start_line: int | None,
    rules: CompiledCoverRules | None = None,
) -> Any:
    """Scan backward from ``provisional_end`` to find the first reliable body root."""
    from edgar_sec.engine.forms.cover.models import BodyRoot

    if provisional_end <= 0:
        return None
    rules = rules or compile_cover_rules()
    search_start = max(
        0,
        provisional_end - _BACKWARD_SEARCH_LIMIT,
        cover_start_line if cover_start_line is not None else 0,
    )
    start = min(provisional_end, len(lines) - 1)
    first_semantic: Any = None
    first_substantive: Any = None
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
        if in_table or is_toc_like_line(stripped):
            continue
        match = match_structural_line(stripped, index)
        if match is not None and match.is_exact_heading:
            following = next_nonblank_line(lines, index + 1)
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


def _find_body_prose_line(
    lines: list[str],
    start_line: int,
    search_limit: int,
    rules: object,
) -> int | None:
    """First logical unit with decisive body-lexical evidence (score >= 2).

    Accumulates consecutive prose lines into bounded paragraphs so wrapped
    text reaches the lexical gate, skipping tagged tables and TOC-like lines.
    """
    buffer: list[str] = []
    buffer_start: int | None = None
    in_table = False

    def score_and_check() -> int | None:
        nonlocal buffer, buffer_start
        if not buffer or buffer_start is None:
            return None
        paragraph = " ".join(line for line in buffer if line)
        if len(paragraph.split()) < 8:
            return None
        score = _score_body_paragraph(paragraph, rules.lexical)
        if score.score >= 2:
            return buffer_start
        return None

    for index in range(max(0, start_line), min(search_limit, len(lines))):
        stripped = lines[index].strip()
        upper = stripped.upper()
        if "<TABLE" in upper:
            in_table = True
            result = _return_with_heading(
                result=score_and_check(), lines=lines, rules=rules
            )
            if result is not None:
                return result
            buffer = []
            buffer_start = None
            continue
        if "</TABLE" in upper:
            in_table = False
            continue
        if in_table or is_toc_like_line(stripped):
            continue
        if not stripped:
            result = _return_with_heading(
                result=score_and_check(), lines=lines, rules=rules
            )
            if result is not None:
                return result
            buffer = []
            buffer_start = None
            continue
        if not buffer:
            buffer_start = index
        buffer.append(stripped)
        if len(" ".join(buffer).split()) >= 160:
            result = _return_with_heading(
                result=score_and_check(), lines=lines, rules=rules
            )
            if result is not None:
                return result
            buffer = []
            buffer_start = None
    return _return_with_heading(result=score_and_check(), lines=lines, rules=rules)


def _return_with_heading(
    result: int | None, lines: list[str], rules: object
) -> int | None:
    """Walk a scored prose start back over preceding body-semantic headings."""
    if result is None:
        return None
    position = result
    for back in range(result - 1, max(0, result - 5) - 1, -1):
        line = lines[back].strip()
        if not line:
            continue
        if len(line) > 70:
            break
        if not rules.body_semantic.search(line):
            break
        if is_toc_like_line(line):
            break
        position = back
    return position


def _unknown(method: BoundaryMethod = BoundaryMethod.UNKNOWN) -> CoverBoundary:
    """Return an undetermined boundary carrying the supplied method."""
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
        adjusted_end, adjusted_evidence = confirm_backward_body(
            lines, end_line, cover_start.start_line, evidence, rules
        )
    else:
        adjusted_end, adjusted_evidence = end_line, evidence
    return CoverBoundary(
        end_line=adjusted_end,
        end_offset=line_offset(lines, adjusted_end),
        method=method,
        confidence=confidence,
        evidence=tuple(adjusted_evidence),
        start_line=cover_start.start_line,
        start_offset=cover_start.start_offset,
        start_evidence=cover_start.evidence,
        approximate=True,
        continued_cover=continued_cover,
    )


__all__ = [
    "confirm_backward_body",
    "enabled",
    "find_cover_start",
    "is_proxy_reference_disclosure",
    "is_toc_like_line",
    "line_at_offset",
    "line_offset",
    "next_nonblank_line",
    "prev_nonblank_line",
]
