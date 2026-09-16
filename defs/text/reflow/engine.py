"""Conservative ASCII prose reflow and untagged-table tagging engine."""

from __future__ import annotations

import re

from defs.tables.protection import (
    _SENTINEL_PREFIX,
    mask_tagged_tables,
    restore_tagged_tables,
)
from defs.text.healing import NEGATIVE_BOUNDARY_RE

from .classifier import _decide
from .features import _compute_features
from .types import (
    ACTION_PRESERVE,
    ACTION_TAG_AND_PRESERVE,
    ACTION_UNWRAP,
    ReflowResult,
    SpanDecision,
)

_TERMINAL_PUNCT = re.compile(r"[.!?][\"\x27\u201d\u2019)]?\s*$")


def _render_block(action: str, lines: tuple[str, ...]) -> str:
    if action == ACTION_UNWRAP:
        non_blank = [line for line in lines if line.strip()]
        if not non_blank:
            return "\n".join(lines)
        first = non_blank[0]
        base_indent = first[: len(first) - len(first.lstrip())]
        parts = [first.strip(), *(line.strip() for line in non_blank[1:])]
        return base_indent + " ".join(parts)
    if action == ACTION_TAG_AND_PRESERVE:
        return "<TABLE>\n" + "\n".join(lines) + "\n</TABLE>"
    return "\n".join(lines)


def _segment(
    lines: list[str],
) -> list[tuple[int, int, tuple[str, ...]]]:
    """Group into blocks of consecutive non-blank lines (blank lines excluded)."""
    blocks: list[tuple[int, int, tuple[str, ...]]] = []
    current: list[str] = []
    start = 0
    for index, line in enumerate(lines):
        if line.strip():
            if not current:
                start = index
            current.append(line)
        elif current:
            blocks.append((start, index, tuple(current)))
            current = []
    if current:
        blocks.append((start, len(lines), tuple(current)))
    return blocks


def _merge_bridged_tables(
    decisions: list[SpanDecision],
    max_blank_lines: int = 1,
) -> list[SpanDecision]:
    """Merge adjacent TAG_AND_PRESERVE blocks across a bounded blank line."""
    if len(decisions) < 2:
        return decisions
    merged: list[SpanDecision] = []
    for decision in decisions:
        previous = merged[-1] if merged else None
        if (
            previous is not None
            and previous.action == ACTION_TAG_AND_PRESERVE
            and decision.action == ACTION_TAG_AND_PRESERVE
            and 0 < decision.start_line - previous.end_line <= max_blank_lines
        ):
            merged[-1] = SpanDecision(
                ACTION_TAG_AND_PRESERVE,
                previous.start_line,
                decision.end_line,
                min(previous.confidence, decision.confidence),
                previous.evidence + ("bridged_blank_line",),
                previous.trace,
            )
            continue
        merged.append(decision)
    return merged


def _try_unify_table_prose(
    decisions: list[SpanDecision],
    blocks: list[tuple[int, int, tuple[str, ...]]],
    decision_index: int,
    skip_decision_indices: set[int],
    group: list[tuple[int, int, tuple[str, ...]]],
) -> tuple[str, ...] | None:
    is_table = decisions[decision_index].action == ACTION_TAG_AND_PRESERVE or any(
        _SENTINEL_PREFIX in line for _, _, b_lines in group for line in b_lines
    )
    if not (
        is_table
        and 0 < decision_index < len(decisions) - 1
        and (decision_index + 1) not in skip_decision_indices
        and decisions[decision_index - 1].action != ACTION_TAG_AND_PRESERVE
        and decisions[decision_index + 1].action != ACTION_TAG_AND_PRESERVE
    ):
        return None
    prev_g = [
        (s, e, b)
        for s, e, b in blocks
        if decisions[decision_index - 1].start_line <= s
        and e <= decisions[decision_index - 1].end_line
    ]
    next_g = [
        (s, e, b)
        for s, e, b in blocks
        if decisions[decision_index + 1].start_line <= s
        and e <= decisions[decision_index + 1].end_line
    ]
    if any(_SENTINEL_PREFIX in line for _, _, b in prev_g for line in b) or any(
        _SENTINEL_PREFIX in line for _, _, b in next_g for line in b
    ):
        return None
    prev_nb = [line for _, _, b in prev_g for line in b if line.strip()]
    next_nb = [line for _, _, b in next_g for line in b if line.strip()]
    if not (
        prev_nb
        and next_nb
        and not _TERMINAL_PUNCT.search(prev_nb[-1])
        and next_nb[0][:1].islower()
        and not NEGATIVE_BOUNDARY_RE.search(next_nb[0])
    ):
        return None
    token = next_nb[0].split()[0] if next_nb[0].split() else ""
    if len(token) > 1 or token == "a":
        return tuple(
            [line for _, _, b in prev_g for line in b]
            + [line for _, _, b in next_g for line in b]
        )
    return None


def reflow_ascii(
    text: str,
    *,
    body_start_line: int | None = None,
    page_analysis: object | None = None,
) -> ReflowResult:
    """Run the conservative gate cascade over plain-text filing content."""
    if not text or "\n" not in text or body_start_line is None:
        return ReflowResult(text)

    page_context = bool(getattr(page_analysis, "page_number_runs", ()))
    masked, spans = mask_tagged_tables(text)
    lines = masked.split("\n")
    blocks = _segment(lines)
    per_block: list[tuple[tuple[int, int, tuple[str, ...]], SpanDecision]] = []
    for start, end, block_lines in blocks:
        if end <= body_start_line:
            per_block.append(
                (
                    (start, end, block_lines),
                    SpanDecision(
                        ACTION_PRESERVE,
                        start,
                        end,
                        1.0,
                        ("pre_body_region",),
                        "fast_noop",
                    ),
                )
            )
            continue
        features = _compute_features(block_lines)
        has_masked = any(_SENTINEL_PREFIX in line for line in block_lines)
        decision = _decide(features, len(block_lines), has_masked)
        if page_context and decision.action == ACTION_UNWRAP:
            decision = SpanDecision(
                decision.action,
                decision.start_line,
                decision.end_line,
                decision.confidence,
                decision.evidence + ("page_boundary_context",),
                decision.trace,
            )
        per_block.append(
            (
                (start, end, block_lines),
                SpanDecision(
                    decision.action,
                    start,
                    end,
                    decision.confidence,
                    decision.evidence,
                    decision.trace,
                ),
            )
        )

    decisions = _merge_bridged_tables([decision for _, decision in per_block])
    rendered: list[str] = []
    cursor = decision_index = 0
    skip_decision_indices: set[int] = set()

    while decision_index < len(decisions):
        if decision_index in skip_decision_indices:
            cursor = decisions[decision_index].end_line
            decision_index += 1
            continue

        decision = decisions[decision_index]
        group = [
            (s, e, b)
            for s, e, b in blocks
            if decision.start_line <= s and e <= decision.end_line
        ]

        unified = _try_unify_table_prose(
            decisions, blocks, decision_index, skip_decision_indices, group
        )
        if unified is not None:
            if rendered:
                rendered.pop()
            rendered.append(_render_block(ACTION_UNWRAP, unified))
            skip_decision_indices.add(decision_index + 1)

        if decision.start_line > cursor:
            rendered.append("\n".join(lines[cursor : decision.start_line]))

        if decision.action == ACTION_TAG_AND_PRESERVE and len(group) > 1:
            merged_lines: list[str] = []
            for pos, (s, e, b) in enumerate(group):
                if pos:
                    merged_lines.extend(lines[group[pos - 1][1] : s])
                merged_lines.extend(b)
            rendered.append(_render_block(decision.action, tuple(merged_lines)))
        else:
            for _, _, block_lines in group:
                rendered.append(_render_block(decision.action, block_lines))
        cursor = decision.end_line
        decision_index += 1

    if cursor < len(lines):
        rendered.append("\n".join(lines[cursor:]))

    result_text = restore_tagged_tables("\n".join(rendered), spans)
    return ReflowResult(result_text, tuple(decisions), spans)


__all__ = [
    "reflow_ascii",
]
