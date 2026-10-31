"""Deciding where a table's narrative ends and its grid begins.
`split_structural_table_intro` unwraps an introducing sentence and keeps the aligned lines after it;
`is_tableish_block` gates that; `unify_table_prose` rejoins a split sentence only at a safe boundary.
"""

from __future__ import annotations

from edgar_sec.foundation.text.healing import NEGATIVE_BOUNDARY_RE
from edgar_sec.foundation.text.patterns import RE_SENTENCE_TERMINAL

from ...reflow.types import ACTION_TAG_AND_PRESERVE, SpanDecision
from ..patterns import _RE_TABLE_INTRO_CUE
from ..protection.constants import SENTINEL_PREFIX
from ..structural import _RE_WIDE_COLUMN_GAP
from ..tokens import numeric_cell_starts as _numeric_cell_starts

_MAX_PROSE_UNIFY_LINES = 3


def split_structural_table_intro(
    lines: tuple[str, ...],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Separate a narrative block from a following aligned table block."""
    if not lines:
        return (), lines

    for idx, line in enumerate(lines[:4]):
        stripped = line.strip()
        if not stripped:
            continue
        candidate_intro = lines[: idx + 1]
        joined_intro = " ".join(l.strip() for l in candidate_intro if l.strip())
        ends_cue_term = stripped.endswith(":") or bool(
            RE_SENTENCE_TERMINAL.search(stripped)
        )
        if (
            ends_cue_term
            and _RE_TABLE_INTRO_CUE.search(joined_intro)
            and idx + 1 < len(lines)
        ):
            return candidate_intro, lines[idx + 1 :]

    for idx, line in enumerate(lines):
        if not line.strip():
            continue
        gap_count = len(_RE_WIDE_COLUMN_GAP.findall(line))
        has_columns = "\t" in line or gap_count >= 2
        has_numeric = bool(_numeric_cell_starts(line))
        has_dash_rule = line.strip().startswith(("-", "=")) and " " in line.strip()

        if (
            (has_columns and (has_numeric or gap_count >= 2))
            or ("\t" in line and any(char.isalpha() for char in line))
            or has_dash_rule
        ):
            if idx == 0:
                return (), lines
            candidate_intro = lines[:idx]
            joined_intro = " ".join(l.strip() for l in candidate_intro if l.strip())
            last_line = candidate_intro[-1].strip()

            has_cue = bool(_RE_TABLE_INTRO_CUE.search(joined_intro))
            ends_term = bool(
                RE_SENTENCE_TERMINAL.search(last_line)
            ) or last_line.endswith(":")
            if has_cue or (
                ends_term
                and len(candidate_intro) <= 3
                and any(c.isalpha() for c in joined_intro)
            ):
                return candidate_intro, lines[idx:]
            break

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
        SENTINEL_PREFIX in line for _, _, b_lines in group for line in b_lines
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
    if any(SENTINEL_PREFIX in line for line in previous_lines + following_lines):
        return None
    previous_nonblank = [line for line in previous_lines if line.strip()]
    following_nonblank = [line for line in following_lines if line.strip()]
    if not (
        previous_nonblank
        and following_nonblank
        and len(previous_nonblank) <= _MAX_PROSE_UNIFY_LINES
        and len(following_nonblank) <= _MAX_PROSE_UNIFY_LINES
        and not RE_SENTENCE_TERMINAL.search(previous_nonblank[-1])
        and following_nonblank[0][:1].islower()
        and not NEGATIVE_BOUNDARY_RE.search(following_nonblank[0])
    ):
        return None
    token = following_nonblank[0].split()[0]
    if len(token) > 1 or token == "a":
        return tuple(previous_lines + following_lines)
    return None


__all__ = [
    "is_tableish_block",
    "split_structural_table_intro",
    "unify_table_prose",
]
