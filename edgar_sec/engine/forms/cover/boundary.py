"""Cover boundary detection: where cover metadata ends and body prose begins.

The detector runs a cascade of bounded structural signals, strongest first, and
returns the first that produces a confident exclusive end line. Every signal
must corroborate prior cover evidence (at least one identity/layout hit or a
page marker); a structural heading on its own is never sufficient, because
filing bodies contain many isolated PART/ITEM headings.

Signal order, strongest first:

1. ``INCORPORATED_REFERENCE``  annual/foreign cover reference block
2. ``TOC_TRANSITION``          a table-of-contents heading after cover evidence
3. ``PART_FALLBACK``           an isolated PART heading after cover evidence
4. ``ITEM_FALLBACK``           a canonical ITEM heading after cover evidence
5. ``BODY_PROSE_FALLBACK``     decisive body-lexical prose with no anchor

The provisional end from a forward signal is then confirmed (or corrected) by a
backward search for real body prose, so a forward signal that lands late inside
the body is pulled back rather than swallowed.

Departure from v1
-----------------
v1's strongest signal consulted ``find_toc_span`` from a TOC subsystem (v1's
``cover/toc/``, ~914 loc) that has no v2 home. v2 uses the heading-based
``TOC_TRANSITION`` path only, reusing the TOC *primitives* that
:mod:`edgar_sec.engine.tables.toc` already provides. The ``TOC_TRANSITION``
signal therefore still fires, one signal later than v1 and without the
``find_toc_span`` confidence refinement.
"""

from __future__ import annotations

import re

from edgar_sec.domain.forms.vocabulary import (
    COVER_LABELS_FLAT,
    COVER_START_IDENTITY_TERMS,
    COVER_START_SHAPE_TERMS,
)
from edgar_sec.engine.document.page_markers import PageMarkerAnalysis
from edgar_sec.engine.forms.cover.body_evidence import (
    MIN_BODY_SCORE,
    is_body_prose,
    score_body_text,
)
from edgar_sec.engine.forms.cover.body_search import (
    RE_TOC_NUMERIC_LABEL,
    confirm_backward_body,
    is_toc_like_line,
)
from edgar_sec.engine.forms.cover.cover_start import find_cover_start
from edgar_sec.engine.forms.cover.models import (
    BoundaryEvidence,
    BoundaryMethod,
    BoundarySignal,
    CoverBoundary,
    CoverBoundaryPolicy,
    CoverStart,
)
from edgar_sec.engine.forms.cover.structure import (
    is_continuation_prose,
    is_preceding_continuation,
    match_structural_line,
)
from edgar_sec.engine.tables.protection import (
    TAGGED_TABLE_CLOSE_RE,
    TAGGED_TABLE_OPEN_RE,
)
from edgar_sec.engine.tables.toc import (
    RE_ITEM_REFERENCE,
    looks_like_toc_row,
    looks_like_toc_tabular,
)
from edgar_sec.foundation.regex.builder import build_alternation

# Maximum lines between a TOC heading and its first row for the heading to act
# as a cover-terminating transition.
_TOC_TRANSITION_ROW_GAP = 10

# Bounded forward search window for the cover scan.
_SEARCH_WINDOW_FLOOR = 200

# Cover-start cluster scanning bounds.
_COVER_START_SEARCH_WINDOW = 60
_COVER_START_CLUSTER_GAP = 5

# Backward confirmation bounds.
_BACKWARD_SEARCH_LIMIT = 150
_BACKWARD_CONFIRM_WINDOW = 8
_MAX_PARAGRAPH_LINES = 8
_MAX_PARAGRAPH_WORDS = 160

# A standalone TOC heading. ``TABLE OF CONTENTS`` is the canonical label; the
# alternation also admits INDEX TO ... and EXHIBIT INDEX headings.
_TOC_HEADING_ALT = build_alternation(
    [
        r"table\s+of\s+contents",
        r"index\s+to\s+(?:financial\s+statements|exhibits)",
        r"exhibit\s+index",
    ],
    auto_escape=False,
)
RE_TOC_HEADING = re.compile(rf"^\s*(?:{_TOC_HEADING_ALT})\s*\.?\s*$", re.IGNORECASE)

# Incorporation phrases that end an annual/foreign cover.
_INCORPORATED_ALT = build_alternation(
    [
        r"incorporated\s+(?:herein\s+)?by\s+reference",
        r"herein\s+incorporated",
        r"is\s+incorporated",
        r"are\s+incorporated",
        r"set\s+forth\s+(?:in|on)",
        r"appearing\s+in",
        r"included\s+in",
        r"filed\s+herewith\s+as",
        r"filed\s+as\s+(?:an?\s+)?exhibit",
        r"reference\s+(?:is\s+)?(?:hereby\s+)?made\s+to",
        r"refer\s+to",
    ],
    auto_escape=False,
)
RE_INCORPORATED = re.compile(rf"\b{_INCORPORATED_ALT}\b", re.IGNORECASE)

_RE_COVER_IDENTITY = re.compile(
    rf"(?:{re.escape(COVER_START_IDENTITY_TERMS[0])}|"
    rf"{re.escape(COVER_START_IDENTITY_TERMS[1])}|"
    rf"{build_alternation(COVER_LABELS_FLAT, auto_escape=True, never_match_empty=True)})",
    re.IGNORECASE,
)
_RE_COVER_START_IDENTITY = re.compile(
    build_alternation(
        COVER_START_IDENTITY_TERMS, auto_escape=False, never_match_empty=True
    ),
    re.IGNORECASE,
)
_RE_COVER_START_SHAPE = re.compile(
    build_alternation(
        COVER_START_SHAPE_TERMS, auto_escape=True, never_match_empty=True
    ),
    re.IGNORECASE,
)

# Lines describing other sections (inside an incorporated-reference sentence)
# must not trigger the body-prose depth guard.
_REFERENCE_DESCRIPTION_MARKERS = ("incorporated", "portions of")
_QUOTED_SECTION_MARKERS = (
    'headings "',
    'heading "',
    "entitled",
    "titled",
    "sections of",
)

_PROXY_REFERENCE_PREFIXES = (
    "portions of",
    "the information required",
    "information required",
    "see part",
    "refer to",
)


# --------------------------------------------------------------------------
# Line helpers
# --------------------------------------------------------------------------


def _prev_nonblank_line(lines: list[str], start_line: int) -> tuple[int, str] | None:
    for index in range(start_line, -1, -1):
        stripped = lines[index].strip()
        if stripped:
            return index, stripped
    return None


def _next_nonblank_line(lines: list[str], start_line: int) -> tuple[int, str] | None:
    for index in range(start_line, len(lines)):
        stripped = lines[index].strip()
        if stripped:
            return index, stripped
    return None


def _line_offset(lines: list[str], line: int) -> int:
    return sum(len(value) + 1 for value in lines[:line])


def _line_at_offset(text: str, offset: int) -> int:
    return text.count("\n", 0, offset)


def _is_proxy_reference_disclosure(line: str) -> bool:
    stripped = line.strip().lower()
    return bool(
        stripped.startswith(_PROXY_REFERENCE_PREFIXES)
        or "indicate by check mark" in stripped
        or "pursuant to item 405" in stripped
        or "delinquent filers" in stripped
    )


# --------------------------------------------------------------------------
# Forward signals
# --------------------------------------------------------------------------


def _next_cover_transition(
    lines: list[str], start_line: int, search_limit: int
) -> tuple[int, str] | None:
    """Find the next heading that can terminate an incorporated-reference block.

    Standalone PART/ITEM headings inside the reference unit are children
    (reference descriptions), not boundaries. When no proven transition root
    exists in the window, last-child safety applies: the cover ends after the
    final known child rather than before the first ambiguous heading.
    """
    pending_toc_heading: int | None = None
    last_child_line: int | None = None
    for index, line in enumerate(lines[start_line:search_limit], start=start_line):
        if RE_TOC_HEADING.match(line):
            pending_toc_heading = index
            continue
        if pending_toc_heading is not None and looks_like_toc_row(line.strip()):
            if index - pending_toc_heading <= _TOC_TRANSITION_ROW_GAP:
                return pending_toc_heading, "TOC heading"
            pending_toc_heading = None
            continue
        match = match_structural_line(line, index)
        if match is None or not match.is_exact_heading or match.reference_count != 1:
            continue
        if index > 0:
            prev = _prev_nonblank_line(lines, index - 1)
            if prev is not None and is_preceding_continuation(prev[1]):
                last_child_line = index
                continue
        following = _next_nonblank_line(lines, index + 1)
        child = False
        if following is not None:
            next_match = match_structural_line(following[1], following[0])
            if (
                (
                    next_match is not None
                    and next_match.is_exact_heading
                    and next_match.reference_count == 1
                    and next_match.role == match.role
                )
                or is_continuation_prose(following[1])
                or _is_proxy_reference_disclosure(following[1])
            ):
                child = True
        if child:
            last_child_line = index
            continue
        if match.role == "part":
            return index, "PART heading"
        if match.role == "item":
            return index, "ITEM 1 heading"
    if last_child_line is not None:
        end = last_child_line + 1
        while end < search_limit and end < len(lines) and end - last_child_line <= 12:
            stripped = lines[end].strip()
            if not stripped or is_continuation_prose(stripped):
                end += 1
                continue
            break
        return end, "end of incorporated-reference children"
    return None


_BODY_SEMANTIC_HEADINGS = (
    "management's discussion and analysis",
    "risk factors",
    "forward-looking statements",
    "forward looking statements",
    "forward looking information",
    "special note regarding forward-looking",
    "special note regarding forward looking",
    "cautionary statements",
    "cautionary note",
    "safe harbor",
    "glossary of",
    "definitions",
)
_RE_BODY_SEMANTIC_HEADINGS = re.compile(
    build_alternation(_BODY_SEMANTIC_HEADINGS, auto_escape=True),
    re.IGNORECASE,
)


def _first_body_semantic_line(
    lines: list[str], start_line: int, end_line: int
) -> int | None:
    """First body-like semantic heading line between the reference block and the transition.

    Used as a depth guard: forward-looking statements and other body-semantic
    sections sometimes sit between the incorporated-reference block and the
    structural transition. Ending the cover at the transition would pull that
    prose into cover processing, so the boundary ends before it instead.
    """
    in_table = False
    for index in range(max(0, start_line), min(end_line, len(lines))):
        stripped = lines[index].strip()
        if TAGGED_TABLE_OPEN_RE.search(stripped):
            in_table = True
            continue
        if TAGGED_TABLE_CLOSE_RE.search(stripped):
            in_table = False
            continue
        if in_table or not stripped:
            continue
        if (
            looks_like_toc_row(stripped)
            or looks_like_toc_tabular(stripped)
            or RE_ITEM_REFERENCE.match(stripped)
            or RE_TOC_NUMERIC_LABEL.match(stripped)
        ):
            continue
        if not _RE_BODY_SEMANTIC_HEADINGS.search(stripped):
            continue
        lower = stripped.lower()
        if any(marker in lower for marker in ("incorporated", "portions of")):
            continue
        sentence = " ".join(lines[index : min(len(lines), index + 3)]).lower()
        if any(marker in sentence for marker in _QUOTED_SECTION_MARKERS):
            continue
        match = match_structural_line(stripped, index)
        if match is not None and match.is_exact_heading:
            continue
        return index
    return None


def _walk_back_over_headings(lines: list[str], result: int | None) -> int | None:
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
        if is_toc_like_line(line):
            break
        if not is_body_prose(line):
            break
        position = back
    return position


def _find_body_prose_line(
    lines: list[str], start_line: int, search_limit: int
) -> int | None:
    """First logical unit with decisive body-lexical evidence (score >= 2).

    Accumulates consecutive prose lines into bounded paragraphs so wrapped text
    reaches the lexical gate, skipping tagged tables and TOC-like lines.
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
        if score_body_text(paragraph) >= MIN_BODY_SCORE:
            return _walk_back_over_headings(lines, buffer_start)
        return None

    for index in range(max(0, start_line), min(search_limit, len(lines))):
        stripped = lines[index].strip()
        upper = stripped.upper()
        if "<TABLE" in upper:
            in_table = True
            found = score_and_check()
            if found is not None:
                return found
            buffer = []
            buffer_start = None
            continue
        if "</TABLE" in upper:
            in_table = False
            continue
        if in_table or is_toc_like_line(stripped):
            continue
        if not stripped:
            found = score_and_check()
            if found is not None:
                return found
            buffer = []
            buffer_start = None
            continue
        if not buffer:
            buffer_start = index
        buffer.append(stripped)
        if len(" ".join(buffer).split()) >= 160:
            found = score_and_check()
            if found is not None:
                return found
            buffer = []
            buffer_start = None
    return score_and_check()


# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------


def _unknown_boundary(
    method: BoundaryMethod = BoundaryMethod.UNKNOWN,
) -> CoverBoundary:
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
    *,
    continued_cover: bool = False,
    confirm_backward: bool = True,
) -> CoverBoundary:
    """Run backward body confirmation and build the final boundary."""
    if confirm_backward:
        adjusted_end, adjusted_evidence = confirm_backward_body(
            lines, end_line, cover_start.start_line, evidence
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


def find_cover_boundary(
    text: str,
    *,
    signals: tuple[BoundarySignal, ...] = (),
    representation: str = "ascii",
    page_analysis: PageMarkerAnalysis | None = None,
) -> CoverBoundary:
    """Find a conservative, exclusive end for cover-specific processing.

    Never treats a literal phrase as authoritative by itself: every forward
    signal must be corroborated by prior cover evidence. An empty ``signals``
    tuple disables cover parsing and returns an unknown boundary, so the
    checkmark solver is never handed a whole document as its cover region.
    """
    if not signals:
        return _unknown_boundary(BoundaryMethod.DISABLED)

    lines = text.splitlines()
    if not lines:
        return _unknown_boundary()

    policy = CoverBoundaryPolicy(signals=signals)
    cover_start = find_cover_start(text, policy)
    scan_start = cover_start.start_line if cover_start.start_line is not None else 0
    search_limit = max(_SEARCH_WINDOW_FLOOR, int(len(lines) * 0.25))
    scan_start = min(scan_start, search_limit)
    evidence: list[BoundaryEvidence] = []

    first_page: int | None = None
    if BoundarySignal.PAGE_MARKERS in policy.signals and page_analysis is not None:
        page_lines = {
            marker.start_line
            if getattr(marker, "start_line", None) is not None
            else text.count("\n", 0, marker.start)
            for marker in page_analysis.markers
        }
        for index in range(min(search_limit, len(lines))):
            if index in page_lines:
                first_page = index
                evidence.append(
                    BoundaryEvidence(
                        name="first_page_marker",
                        strength=0.45,
                        line=index,
                        details="page marker establishes a lower bound",
                    )
                )
                break

    identity_count = 0
    for line in lines[scan_start:search_limit]:
        if _RE_COVER_IDENTITY.search(line):
            identity_count += 1
    if first_page is not None and identity_count >= 2:
        evidence.append(
            BoundaryEvidence(
                name="cover_identity_layout",
                strength=0.7,
                line=first_page,
                details=f"{identity_count} cover identity signals",
            )
        )

    if BoundarySignal.INCORPORATED_REFERENCE in policy.signals:
        result = _detect_incorporated_reference(
            text,
            lines,
            scan_start,
            search_limit,
            identity_count,
            first_page,
            evidence,
            cover_start,
        )
        if result is not None:
            return result

    if BoundarySignal.TOC_TRANSITION in policy.signals:
        for index, line in enumerate(lines[scan_start:search_limit], start=scan_start):
            if not RE_TOC_HEADING.match(line):
                continue
            if identity_count < 2 and first_page is None:
                continue
            evidence.append(
                BoundaryEvidence(
                    name="toc_transition",
                    strength=0.9,
                    line=index,
                    details="TOC heading follows cover evidence",
                )
            )
            return _finalize_boundary(
                index,
                BoundaryMethod.STRUCTURAL,
                0.9,
                evidence,
                cover_start,
                lines,
            )

    if BoundarySignal.PART_FALLBACK in policy.signals:
        result = _detect_structural_fallback(
            lines,
            scan_start,
            search_limit,
            identity_count,
            first_page,
            evidence,
            cover_start,
            role="part",
        )
        if result is not None:
            return result

    if BoundarySignal.ITEM_FALLBACK in policy.signals:
        result = _detect_structural_fallback(
            lines,
            scan_start,
            search_limit,
            identity_count,
            first_page,
            evidence,
            cover_start,
            role="item",
        )
        if result is not None:
            return result

    if BoundarySignal.BODY_PROSE_FALLBACK in policy.signals:
        prose_line = _find_body_prose_line(lines, scan_start, search_limit)
        if (
            prose_line is not None
            and cover_start.start_line is not None
            and identity_count >= 1
        ):
            evidence.append(
                BoundaryEvidence(
                    name="body_prose_fallback",
                    strength=0.65,
                    line=prose_line,
                    details=(
                        "decisive body-lexical prose ends a cover without "
                        "structural anchors"
                    ),
                )
            )
            return _finalize_boundary(
                prose_line,
                BoundaryMethod.FALLBACK,
                0.65,
                evidence,
                cover_start,
                lines,
            )

    if (
        cover_start.start_line is not None
        and identity_count >= 1
        and len(lines) <= search_limit
    ):
        evidence.append(
            BoundaryEvidence(
                name="cover_only_fragment",
                strength=0.6,
                line=len(lines),
                details=(
                    f"{identity_count} cover identity signal(s), detected cover "
                    "start, and no body anchor in fully searched document"
                ),
            )
        )
        return CoverBoundary(
            end_line=len(lines),
            end_offset=len(text),
            method=BoundaryMethod.FALLBACK,
            confidence=0.6,
            evidence=tuple(evidence),
            start_line=cover_start.start_line,
            start_offset=cover_start.start_offset,
            start_evidence=cover_start.evidence,
            approximate=True,
            continued_cover=True,
        )

    return _unknown_boundary()


def _detect_incorporated_reference(
    text: str,
    lines: list[str],
    scan_start: int,
    search_limit: int,
    identity_count: int,
    first_page: int | None,
    evidence: list[BoundaryEvidence],
    cover_start: CoverStart,
) -> CoverBoundary | None:
    """Signal 1: the annual/foreign cover reference block."""
    for match in RE_INCORPORATED.finditer(text):
        index = _line_at_offset(text, match.start())
        if index < scan_start or index >= search_limit:
            continue
        if identity_count < 2 and first_page is None:
            continue
        if _is_proxy_reference_disclosure(lines[index]):
            continue
        phrase_end_line = _line_at_offset(text, match.end()) + 1
        transition = _next_cover_transition(lines, phrase_end_line, search_limit)
        end_line = transition[0] if transition else phrase_end_line
        depth_line = _first_body_semantic_line(lines, phrase_end_line, end_line)
        if depth_line is not None:
            evidence.append(
                BoundaryEvidence(
                    name="body_prose_depth_adjust",
                    strength=0.7,
                    line=depth_line,
                    details=(
                        "body-semantic prose precedes the structural transition; "
                        "cover ends before it"
                    ),
                )
            )
            end_line = depth_line
        evidence.append(
            BoundaryEvidence(
                name="incorporated_reference",
                strength=0.92 if identity_count >= 2 else 0.72,
                line=index,
                details="annual/foreign cover reference block",
            )
        )
        if transition:
            evidence.append(
                BoundaryEvidence(
                    name="incorporated_reference_transition",
                    strength=0.96,
                    line=end_line,
                    details=f"cover ends before {transition[1]}",
                )
            )
        return _finalize_boundary(
            end_line,
            BoundaryMethod.STRUCTURAL if transition else BoundaryMethod.PHRASE,
            (0.96 if transition else min(0.9, 0.72 + (0.06 * min(identity_count, 3)))),
            evidence,
            cover_start,
            lines,
            continued_cover=True,
        )
    return None


def _detect_structural_fallback(
    lines: list[str],
    scan_start: int,
    search_limit: int,
    identity_count: int,
    first_page: int | None,
    evidence: list[BoundaryEvidence],
    cover_start: CoverStart,
    *,
    role: str,
) -> CoverBoundary | None:
    """Signals 3/4: an isolated PART or ITEM heading after cover evidence."""
    confidence = 0.68 if role == "part" else 0.62
    for index, line in enumerate(lines[scan_start:search_limit], start=scan_start):
        match = match_structural_line(line, index)
        if match is None or match.role != role or not match.is_exact_heading:
            continue
        if identity_count < 2 and first_page is None:
            continue
        if index > 0:
            prev = _prev_nonblank_line(lines, index - 1)
            if prev is not None and is_preceding_continuation(prev[1]):
                continue
        following = _next_nonblank_line(lines, index + 1)
        if following is not None and (
            is_continuation_prose(following[1])
            or _is_proxy_reference_disclosure(following[1])
        ):
            continue
        if role == "part" and following is not None:
            next_match = match_structural_line(following[1], following[0])
            if next_match is not None and next_match.role == "item":
                evidence.append(
                    BoundaryEvidence(
                        name="part_item_pair",
                        strength=0.85,
                        line=following[0],
                        details="PART I followed by ITEM 1 business-title heading",
                    )
                )
        evidence.append(
            BoundaryEvidence(
                name=f"{role}_transition",
                strength=confidence,
                line=index,
                details=f"structural {role.upper()}/ITEM candidate after cover evidence",
            )
        )
        return _finalize_boundary(
            index,
            BoundaryMethod.FALLBACK,
            confidence,
            evidence,
            cover_start,
            lines,
        )
    return None


__all__ = [
    "RE_INCORPORATED",
    "RE_TOC_HEADING",
    "RE_TOC_NUMERIC_LABEL",
    "find_cover_boundary",
    "find_cover_start",
    "is_toc_like_line",
]
