"""Table-specific policies used by the generic ASCII reflow coordinator."""

from __future__ import annotations

import re

from defs.regex import build_alternation
from defs.tables.protection import _SENTINEL_PREFIX
from defs.text.healing import NEGATIVE_BOUNDARY_RE
from defs.text.patterns import RE_SENTENCE_TERMINAL, RE_SEPARATOR_LINE

from .features import _compute_features, _numeric_cell_starts
from .types import (
    ACTION_PRESERVE,
    ACTION_TAG_AND_PRESERVE,
    ACTION_UNWRAP,
    ReflowPolicy,
    SpanDecision,
)

_RE_WIDE_COLUMN_GAP = re.compile(r"\s{3,}")
_TABLE_INTRO_NOUNS = build_alternation(
    (
        "table",
        "tables",
        "schedule",
        "schedules",
        "information",
        "data",
        "amounts",
        "analysis",
        "summary",
        "breakdown",
        "reconciliation",
    ),
    auto_escape=True,
)
_TABLE_INTRO_LAYOUT_NOUNS = build_alternation(
    ("table", "tables", "schedule", "schedules"), auto_escape=True
)
_TABLE_INTRO_TABLE_VERBS = build_alternation(
    ("below", "above", "presents", "present", "shows", "show", "sets forth"),
    auto_escape=True,
)
_TABLE_INTRO_FOLLOWING = build_alternation(
    ("below", "in the following"), auto_escape=True
)
_TABLE_INTRO_DISPLAY_VERBS = build_alternation(
    ("presented", "shown", "summarized"), auto_escape=True
)
_TABLE_INTRO_RELATION = build_alternation(("as", "are"), auto_escape=True)
_TABLE_INTRO_COLLECTION_VERBS = build_alternation(
    ("consists", "includes"), auto_escape=True
)
_TABLE_INTRO_PATTERNS = (
    rf"the\s+following\s+(?:{_TABLE_INTRO_NOUNS})",
    rf"the\s+(?:{_TABLE_INTRO_LAYOUT_NOUNS})\s+(?:{_TABLE_INTRO_TABLE_VERBS})",
    rf"{_TABLE_INTRO_RELATION}\s+follows",
    rf"set\s+forth\s+(?:{_TABLE_INTRO_FOLLOWING})",
    rf"(?:{_TABLE_INTRO_DISPLAY_VERBS})\s+(?:{_TABLE_INTRO_FOLLOWING})",
    rf"(?:{_TABLE_INTRO_COLLECTION_VERBS})\s+of\s+the\s+following",
)
_RE_TABLE_INTRO_CUE = re.compile(
    rf"\b(?:{build_alternation(_TABLE_INTRO_PATTERNS)})\b",
    re.IGNORECASE,
)


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
    for index, line in enumerate(lines):
        if index == 0 or not line.strip():
            continue
        gap_count = len(_RE_WIDE_COLUMN_GAP.findall(line))
        has_columns = "\t" in line or gap_count >= 2
        has_numeric = bool(_numeric_cell_starts(line))
        prefix_nonblank = sum(bool(item.strip()) for item in lines[:index])
        if prefix_nonblank >= 1 and has_columns and (has_numeric or gap_count >= 2):
            return lines[:index], lines[index:]
        if (
            prefix_nonblank >= 1
            and "\t" in line
            and any(char.isalpha() for char in line)
        ):
            return lines[:index], lines[index:]
    return (), lines


def is_tableish_block(features: object) -> bool:
    """Identify generic aligned/numeric table blocks before prose relaxation."""
    numeric_rows = len(getattr(features, "numeric_cell_rows", ()))
    gap_rows = len(getattr(features, "gap_start_rows", ()))
    return bool(
        getattr(features, "has_separator", False)
        and (numeric_rows >= 1 or gap_rows >= 2)
        or numeric_rows >= 3
        and gap_rows >= 2
        and getattr(features, "shared_numeric_columns", 0) >= 2
    )


def _is_header_prefix(lines: tuple[str, ...]) -> bool:
    nonblank = tuple(line.strip() for line in lines if line.strip())
    if not nonblank or len(nonblank) > 4:
        return False
    if any(RE_SENTENCE_TERMINAL.search(line) for line in nonblank):
        return False
    if any(line.startswith(("<", "/", "o ", "- ", "* ")) for line in nonblank):
        return False
    return all(len(line.split()) <= 8 for line in nonblank) and any(
        "\t" in line or _RE_WIDE_COLUMN_GAP.search(line) or line[:1].isspace()
        for line in lines
    )


def expand_table_headers(
    decisions: list[SpanDecision],
    blocks: list[tuple[int, int, tuple[str, ...]]],
) -> list[SpanDecision]:
    """Absorb a short geometry-compatible title/header before an inferred table."""
    expanded = list(decisions)
    for index, decision in enumerate(tuple(expanded)):
        if (
            decision.action != ACTION_TAG_AND_PRESERVE
            or "inferred_table_layout" not in decision.evidence
        ):
            continue
        if index == 0:
            continue
        previous = expanded[index - 1]
        if (
            previous.action != ACTION_PRESERVE
            or decision.start_line - previous.end_line > 3
        ):
            continue
        prefix = _block_lines(blocks, previous)
        table_lines = _block_lines(blocks, decision)
        table_features = _compute_features(table_lines)
        if not _is_header_prefix(prefix) or not table_features.numeric_cell_rows:
            continue
        expanded[index] = SpanDecision(
            ACTION_TAG_AND_PRESERVE,
            previous.start_line,
            decision.end_line,
            min(previous.confidence, decision.confidence),
            decision.evidence + ("expanded_table_header",),
            decision.trace,
        )
        expanded[index - 1] = SpanDecision(
            ACTION_PRESERVE,
            previous.start_line,
            previous.start_line,
            previous.confidence,
            ("absorbed_table_header",),
            previous.trace,
        )
    return [
        decision for decision in expanded if decision.start_line < decision.end_line
    ]


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
    prior_positions = tuple(
        position for line in previous for position in _numeric_cell_starts(line)
    )
    next_positions = tuple(
        position for line in continuation for position in _numeric_cell_starts(line)
    )
    if not prior_positions or not next_positions:
        return False
    return any(
        abs(position - prior_position) <= 3
        for position in next_positions
        for prior_position in prior_positions
    )


def _block_lines(
    blocks: list[tuple[int, int, tuple[str, ...]]], decision: SpanDecision
) -> tuple[str, ...]:
    return tuple(
        line
        for start, end, block in blocks
        if decision.start_line <= start and end <= decision.end_line
        for line in block
    )


def _is_structural_table_bridge(lines: tuple[str, ...]) -> bool:
    """Recognize short section labels between parts of one aligned statement."""
    nonblank = tuple(line.strip() for line in lines if line.strip())
    if not nonblank or len(nonblank) > 4:
        return False
    return all(
        len(line) <= 80
        and len(line.split()) <= 10
        and not RE_SENTENCE_TERMINAL.search(line)
        and len(_numeric_cell_starts(line)) < 2
        and not RE_SEPARATOR_LINE.fullmatch(line)
        for line in nonblank
    )


def _is_structural_table_tail(lines: tuple[str, ...]) -> bool:
    """Recognize a final aligned total that follows a statement body."""
    nonblank = tuple(line.strip() for line in lines if line.strip())
    return bool(
        nonblank
        and any(RE_SEPARATOR_LINE.fullmatch(line) for line in nonblank)
        and any(len(_numeric_cell_starts(line)) >= 2 for line in nonblank)
    )


def merge_bridged_tables(
    decisions: list[SpanDecision],
    blocks: list[tuple[int, int, tuple[str, ...]]] | None = None,
    max_blank_lines: int = 1,
    policy: ReflowPolicy | None = None,
) -> list[SpanDecision]:
    """Merge adjacent table spans across bounded blanks, markers, or separators."""
    if len(decisions) < 2:
        return decisions
    merged: list[SpanDecision] = []
    index = 0
    while index < len(decisions):
        decision = decisions[index]
        previous = merged[-1] if merged else None
        if (
            blocks is not None
            and previous is not None
            and previous.action == ACTION_TAG_AND_PRESERVE
        ):
            continuation = _block_lines(blocks, decision)
            prior = _block_lines(blocks, previous)
            if (
                decision.start_line - previous.end_line <= 1
                and is_table_row_continuation(prior, continuation, policy)
            ):
                merged[-1] = SpanDecision(
                    ACTION_TAG_AND_PRESERVE,
                    previous.start_line,
                    decision.end_line,
                    min(previous.confidence, 0.75),
                    previous.evidence + ("bridged_blank_line",),
                    previous.trace,
                )
                index += 1
                continue
        if (
            blocks is not None
            and previous is not None
            and previous.action == ACTION_TAG_AND_PRESERVE
            and decision.action == ACTION_PRESERVE
            and index + 1 < len(decisions)
            and decisions[index + 1].action == ACTION_PRESERVE
        ):
            middle_lines = tuple(
                line.strip()
                for start, end, block in blocks
                if decision.start_line <= start and end <= decision.end_line
                for line in block
                if line.strip()
            )
            following = decisions[index + 1]
            following_features = _compute_features(_block_lines(blocks, following))
            if (
                middle_lines
                and all(RE_SEPARATOR_LINE.fullmatch(line) for line in middle_lines)
                and 1 <= len(following_features.numeric_cell_rows) < 3
                and following.start_line - previous.end_line <= 3
            ):
                merged[-1] = SpanDecision(
                    ACTION_TAG_AND_PRESERVE,
                    previous.start_line,
                    following.end_line,
                    min(previous.confidence, 0.75),
                    previous.evidence + ("bridged_table_separator",),
                    previous.trace,
                )
                index += 2
                continue
        if (
            blocks is not None
            and previous is not None
            and previous.action == ACTION_TAG_AND_PRESERVE
            and decision.action in (ACTION_PRESERVE, ACTION_UNWRAP)
        ):
            following_index = index
            bridge_lines: list[str] = []
            while following_index < len(decisions) and decisions[
                following_index
            ].action in (ACTION_PRESERVE, ACTION_UNWRAP):
                bridge_lines.extend(_block_lines(blocks, decisions[following_index]))
                following_index += 1
            if following_index >= len(decisions):
                merged.append(decision)
                index += 1
                continue
            following = decisions[following_index]
            if (
                following.action == ACTION_TAG_AND_PRESERVE
                and _is_structural_table_bridge(tuple(bridge_lines))
                and following.start_line - previous.end_line <= 8
            ):
                merged[-1] = SpanDecision(
                    ACTION_TAG_AND_PRESERVE,
                    previous.start_line,
                    following.end_line,
                    min(previous.confidence, following.confidence, 0.75),
                    previous.evidence + ("bridged_structural_section",),
                    previous.trace,
                )
                index = following_index + 1
                continue
        if (
            previous is not None
            and previous.action == ACTION_TAG_AND_PRESERVE
            and decision.action == ACTION_TAG_AND_PRESERVE
            and 0 <= decision.start_line - previous.end_line <= max_blank_lines
        ):
            merged[-1] = SpanDecision(
                ACTION_TAG_AND_PRESERVE,
                previous.start_line,
                decision.end_line,
                min(previous.confidence, decision.confidence),
                previous.evidence + ("bridged_blank_line",),
                previous.trace,
            )
            index += 1
            continue
        if (
            blocks is not None
            and previous is not None
            and previous.action == ACTION_TAG_AND_PRESERVE
            and decision.action == ACTION_PRESERVE
            and index + 1 < len(decisions)
            and decisions[index + 1].action == ACTION_TAG_AND_PRESERVE
        ):
            middle_lines = [
                line.strip()
                for start, end, block in blocks
                if decision.start_line <= start and end <= decision.end_line
                for line in block
                if line.strip()
            ]
            if (
                middle_lines
                and policy is not None
                and all(
                    policy.is_page_boundary_line is not None
                    and policy.is_page_boundary_line(line)
                    for line in middle_lines
                )
            ):
                following = decisions[index + 1]
                merged[-1] = SpanDecision(
                    ACTION_TAG_AND_PRESERVE,
                    previous.start_line,
                    following.end_line,
                    min(previous.confidence, following.confidence),
                    previous.evidence + ("bridged_page_marker",),
                    previous.trace,
                )
                index += 2
                continue
        merged.append(decision)
        index += 1
    return merged


def merge_structural_table_regions(
    decisions: list[SpanDecision],
    blocks: list[tuple[int, int, tuple[str, ...]]],
) -> list[SpanDecision]:
    """Coalesce table decisions separated by short structural blocks."""
    result: list[SpanDecision] = []
    index = 0
    while index < len(decisions):
        current = decisions[index]
        if current.action != ACTION_TAG_AND_PRESERVE:
            result.append(current)
            index += 1
            continue
        next_index = index + 1
        while next_index < len(decisions) and next_index <= index + 8:
            candidate = decisions[next_index]
            if candidate.action == ACTION_TAG_AND_PRESERVE:
                middle = tuple(
                    line
                    for decision in decisions[index + 1 : next_index]
                    for line in _block_lines(blocks, decision)
                )
                if (
                    _is_structural_table_bridge(middle)
                    and candidate.start_line - current.end_line <= 8
                ):
                    tail_index = next_index + 1
                    if tail_index < len(decisions):
                        tail_lines = _block_lines(blocks, decisions[tail_index])
                        if _is_structural_table_tail(tail_lines):
                            current = SpanDecision(
                                ACTION_TAG_AND_PRESERVE,
                                current.start_line,
                                decisions[tail_index].end_line,
                                min(current.confidence, candidate.confidence, 0.75),
                                current.evidence
                                + ("bridged_structural_section", "included_table_tail"),
                                current.trace,
                            )
                            next_index = tail_index + 2
                            result.append(current)
                            index = next_index
                            continue
                    current = SpanDecision(
                        ACTION_TAG_AND_PRESERVE,
                        current.start_line,
                        candidate.end_line,
                        min(current.confidence, candidate.confidence, 0.75),
                        current.evidence + ("bridged_structural_section",),
                        current.trace,
                    )
                    next_index += 1
                    break
                break
            next_index += 1
        result.append(current)
        index = (
            next_index if current.end_line != decisions[index].end_line else index + 1
        )
    return result


def extend_multiline_table_rows(
    decisions: list[SpanDecision],
    blocks: list[tuple[int, int, tuple[str, ...]]],
    policy: ReflowPolicy | None = None,
) -> list[SpanDecision]:
    """Extend a table span through wrapped description and numeric row blocks."""
    extended: list[SpanDecision] = []
    index = 0
    while index < len(decisions):
        decision = decisions[index]
        if decision.action != ACTION_TAG_AND_PRESERVE:
            extended.append(decision)
            index += 1
            continue
        current_lines = _block_lines(blocks, decision)
        current_features = _compute_features(current_lines)
        if (
            len(current_features.numeric_cell_rows) >= 3
            and current_lines
            and RE_SEPARATOR_LINE.fullmatch(current_lines[-1].strip())
        ):
            extended.append(decision)
            index += 1
            continue
        end_line = decision.end_line
        saw_numeric_tail = False
        next_index = index + 1
        while next_index < len(decisions) and next_index <= index + 12:
            candidate = decisions[next_index]
            if candidate.action == ACTION_TAG_AND_PRESERVE:
                break
            candidate_lines = _block_lines(blocks, candidate)
            stripped = tuple(line.strip() for line in candidate_lines if line.strip())
            if not stripped:
                next_index += 1
                continue
            if all(
                policy is not None
                and policy.is_page_boundary_line is not None
                and policy.is_page_boundary_line(line)
                for line in stripped
            ):
                end_line = candidate.end_line
                next_index += 1
                continue
            candidate_features = _compute_features(candidate_lines)
            numeric_tail = bool(candidate_features.numeric_cell_rows)
            lookahead_numeric = next_index + 1 < len(decisions) and bool(
                _compute_features(
                    _block_lines(blocks, decisions[next_index + 1])
                ).numeric_cell_rows
            )
            if not numeric_tail and not lookahead_numeric:
                break
            end_line = candidate.end_line
            saw_numeric_tail = saw_numeric_tail or numeric_tail
            next_index += 1
            if saw_numeric_tail and RE_SEPARATOR_LINE.fullmatch(stripped[-1]):
                break
        if next_index > index + 1 and saw_numeric_tail:
            extended.append(
                SpanDecision(
                    ACTION_TAG_AND_PRESERVE,
                    decision.start_line,
                    end_line,
                    min(decision.confidence, 0.75),
                    decision.evidence + ("extended_multiline_rows",),
                    decision.trace,
                )
            )
            index = next_index
            continue
        extended.append(decision)
        index += 1
    return extended


__all__ = [
    "expand_table_headers",
    "extend_multiline_table_rows",
    "is_table_row_continuation",
    "is_tableish_block",
    "merge_bridged_tables",
    "merge_structural_table_regions",
    "split_structural_table_intro",
    "unify_table_prose",
]
