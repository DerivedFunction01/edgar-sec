"""Cover transition detection logic."""

from __future__ import annotations

from defs.sec_forms.cover.body_search import _next_nonblank_line
from defs.sec_forms.cover.structure import (
    RE_ITEM_REFERENCE,
    is_continuation_prose,
    is_preceding_continuation,
    match_structural_line,
)
from defs.sec_forms.cover.toc import (
    RE_TOC_HEADING,
    RE_TOC_NUMERIC_LABEL,
    looks_like_toc_row,
    looks_like_toc_tabular,
)

from .helpers import (
    _QUOTED_SECTION_MARKERS,
    _RE_TAGGED_TABLE_CLOSE,
    _RE_TAGGED_TABLE_OPEN,
    _TOC_TRANSITION_ROW_GAP,
    _is_proxy_reference_disclosure,
    _prev_nonblank_line,
)


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
        if match is None:
            continue
        if not match.is_exact_heading:
            continue
        if match.reference_count != 1:
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


def _first_body_semantic_line(
    lines: list[str],
    start_line: int,
    end_line: int,
    rules: object,
) -> int | None:
    """First prose line between the reference block and the transition that is body-like.

    Used as a depth guard: forward-looking statements and other body-semantic
    sections sometimes sit between the incorporated-reference block and the
    structural transition. Ending the cover at the transition would pull that
    prose into cover healing, so the boundary ends before it instead.
    """
    in_table = False
    for index in range(max(0, start_line), min(end_line, len(lines))):
        stripped = lines[index].strip()
        if _RE_TAGGED_TABLE_OPEN.search(stripped):
            in_table = True
            continue
        if _RE_TAGGED_TABLE_CLOSE.search(stripped):
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
        if not rules.body_semantic.search(stripped):
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
