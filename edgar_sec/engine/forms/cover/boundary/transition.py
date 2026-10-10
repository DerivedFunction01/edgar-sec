"""Cover transition detection: a cover does not end at the first heading after an
incorporated-reference block, because that block lists the filing's own parts as
children. The resolver demands a proven root, else ends after the last child.
"""

from __future__ import annotations

from edgar_sec.engine.forms.cover.structure import (
    RE_ITEM_REFERENCE,
    is_continuation_prose,
    is_preceding_continuation,
    match_structural_line,
)
from edgar_sec.engine.tables.toc.patterns import (
    looks_like_toc_row,
    looks_like_toc_tabular,
)
from edgar_sec.engine.tables.protection.tags import (
    TAGGED_TABLE_CLOSE_RE,
    TAGGED_TABLE_OPEN_RE,
)

from ..toc.patterns import RE_TOC_HEADING, RE_TOC_NUMERIC_LABEL
from .corridor import (
    is_proxy_reference_disclosure,
    next_nonblank_line,
    prev_nonblank_line,
)

# Maximum lines between a TOC heading and its first row for the heading to act
# as an incorporated-reference transition; mirrors the TOC span gap gate.
_TOC_TRANSITION_ROW_GAP = 10

# Lines describing other sections (for example inside an incorporated-reference
# sentence) must not trigger the body-prose depth guard.
_QUOTED_SECTION_MARKERS = (
    'headings "',
    'heading "',
    "entitled",
    "titled",
    "sections of",
)


def _next_cover_transition(
    lines: list[str], start_line: int, search_limit: int
) -> tuple[int, str] | None:
    """The next heading terminating an incorporated-reference block; standalone
    PART/ITEM headings inside it are children, so the cover ends after the last.
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
            prev = prev_nonblank_line(lines, index - 1)
            if prev is not None and is_preceding_continuation(prev[1]):
                last_child_line = index
                continue
        following = next_nonblank_line(lines, index + 1)
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
                or is_proxy_reference_disclosure(following[1])
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
    """The first body-like prose line before the transition: a depth guard, since
    ending the cover there would pull body prose into cover healing.
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


__all__ = ["_first_body_semantic_line", "_next_cover_transition"]
