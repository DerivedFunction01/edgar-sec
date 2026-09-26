"""Table-specific policies used by the generic ASCII reflow coordinator."""

from __future__ import annotations

from defs.tables.numeric_cells import is_numeric_cell
from defs.tables.patterns import TABLE_INTRO_CUE_RE as _RE_TABLE_INTRO_CUE
from defs.tables.protection import _SENTINEL_PREFIX
from defs.tables.structural import (
    _RE_WIDE_COLUMN_GAP,
)
from defs.tables.tokens import numeric_cell_starts as _numeric_cell_starts
from defs.text.healing.lines import NEGATIVE_BOUNDARY_RE
from defs.text.reflow.types import (
    ACTION_TAG_AND_PRESERVE,
    ReflowPolicy,
    SpanDecision,
)
from defs.text.structure.patterns import RE_SENTENCE_TERMINAL, RE_SEPARATOR_LINE


def split_structural_table_intro(
    lines: tuple[str, ...],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Separate a narrative block from a following aligned table block."""
    first_nonblank = next((line for line in lines if line.strip()), "")
    if not first_nonblank or not (
        RE_SENTENCE_TERMINAL.search(first_nonblank)
        or _RE_TABLE_INTRO_CUE.search(first_nonblank)
    ):
        return (), lines
    prefix_nonblank = 0
    for index, line in enumerate(lines):
        if not line.strip():
            continue
        if prefix_nonblank >= 1:
            gap_count = len(_RE_WIDE_COLUMN_GAP.findall(line))
            has_columns = "\t" in line or gap_count >= 2
            has_numeric = bool(_numeric_cell_starts(line))
            if has_columns and (has_numeric or gap_count >= 2):
                return lines[:index], lines[index:]
            if "\t" in line and any(char.isalpha() for char in line):
                return lines[:index], lines[index:]
        prefix_nonblank += 1
    return (), lines


def is_tableish_block(features: object) -> bool:
    """Identify generic aligned/numeric table blocks before prose relaxation."""
    gap_rows = len(getattr(features, "gap_start_rows", ()))
    has_tab = getattr(features, "has_tab", False)
    shared_cols = getattr(features, "shared_numeric_columns", 0)
    if not (gap_rows >= 1 or has_tab or shared_cols >= 1):
        return False
    numeric_rows = len(getattr(features, "numeric_cell_rows", ()))
    return bool(
        getattr(features, "has_separator", False)
        and (numeric_rows >= 1 or gap_rows >= 2)
        or numeric_rows >= 3
        and gap_rows >= 2
        and shared_cols >= 2
    )


def unify_table_prose(
    decisions: list[SpanDecision],
    blocks: list[tuple[int, int, tuple[str, ...]]],
    decision_index: int,
    skip_decision_indices: set[int],
    group: list[tuple[int, int, tuple[str, ...]]],
) -> tuple[str, ...] | None:
    """Join a table block to adjacent prose only at a safe sentence boundary."""
    is_table = decisions[decision_index].action == ACTION_TAG_AND_PRESERVE or any(
        _SENTINEL_PREFIX in line for _, _, b_lines in group for line in b_lines
    )
    if not (
        is_table
        and 0 < decision_index < len(decisions) - 1
        and decision_index + 1 not in skip_decision_indices
        and decisions[decision_index - 1].action != ACTION_TAG_AND_PRESERVE
        and decisions[decision_index + 1].action != ACTION_TAG_AND_PRESERVE
    ):
        return None
    previous = decisions[decision_index - 1]
    following = decisions[decision_index + 1]
    previous_lines = [
        line
        for start, end, block in blocks
        if previous.start_line <= start and end <= previous.end_line
        for line in block
    ]
    following_lines = [
        line
        for start, end, block in blocks
        if following.start_line <= start and end <= following.end_line
        for line in block
    ]
    if any(_SENTINEL_PREFIX in line for line in previous_lines + following_lines):
        return None
    previous_nonblank = [line for line in previous_lines if line.strip()]
    following_nonblank = [line for line in following_lines if line.strip()]
    if not (
        previous_nonblank
        and following_nonblank
        and not RE_SENTENCE_TERMINAL.search(previous_nonblank[-1])
        and following_nonblank[0][:1].islower()
        and not NEGATIVE_BOUNDARY_RE.search(following_nonblank[0])
    ):
        return None
    token = following_nonblank[0].split()[0]
    if len(token) > 1 or token == "a":
        return tuple(previous_lines + following_lines)
    return None


def is_table_row_continuation(
    previous: tuple[str, ...],
    continuation: tuple[str, ...],
    policy: ReflowPolicy | None = None,
) -> bool:
    """Return whether numeric columns indicate a wrapped table row."""
    if not continuation or any(
        policy is not None
        and policy.is_page_boundary_line is not None
        and policy.is_page_boundary_line(line.strip())
        for line in continuation
    ):
        return False
    nonblank = tuple(line.strip() for line in continuation if line.strip())
    if not nonblank:
        return False
    if all(RE_SEPARATOR_LINE.fullmatch(line) for line in nonblank):
        return True
    prior_positions = tuple(
        position for line in previous for position in _numeric_cell_starts(line)
    )
    next_positions = tuple(
        position for line in continuation for position in _numeric_cell_starts(line)
    )
    if not prior_positions or not next_positions:
        return False
    aligned_cells = sum(
        any(abs(position - prior_position) <= 3 for prior_position in prior_positions)
        for position in next_positions
    )
    if aligned_cells >= 2:
        return True
    if aligned_cells < 1 or len(nonblank) > 3:
        return False
    for line in nonblank:
        words = line.split()
        if len(words) > 5 and RE_SENTENCE_TERMINAL.search(line):
            return False
        if RE_SEPARATOR_LINE.match(line):
            continue
        has_total = False
        all_numeric = True
        for w in words:
            if not has_total and w.lower() in ("total", "net", "less", "subtotal"):
                has_total = True
            if all_numeric and not is_numeric_cell(w):
                all_numeric = False
        if not (all_numeric or has_total):
            return False
    return True


def _block_lines(
    blocks: list[tuple[int, int, tuple[str, ...]]], decision: SpanDecision
) -> tuple[str, ...]:
    return tuple(
        line
        for start, end, block in blocks
        if decision.start_line <= start and end <= decision.end_line
        for line in block
    )


__all__ = [
    "is_table_row_continuation",
    "is_tableish_block",
    "split_structural_table_intro",
    "unify_table_prose",
]
