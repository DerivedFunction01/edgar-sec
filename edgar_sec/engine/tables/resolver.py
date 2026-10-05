"""Single-pass table region resolver for generic ASCII reflow.
A grown span must pass a discipline gate before it may be tagged: a protected-table overlap or a
span that does not look like a grid is downgraded. The bias is to preserve.
"""

from __future__ import annotations

import bisect

from edgar_sec.engine.reflow.features.geometry import _compute_features
from edgar_sec.engine.reflow.types import (
    ACTION_PRESERVE,
    ACTION_TAG_AND_PRESERVE,
    ACTION_UNWRAP,
    ReflowPolicy,
    SpanDecision,
)
from edgar_sec.foundation.text.patterns import RE_SEPARATOR_LINE

from .policy.continuation import is_table_row_continuation
from .protection.tags import SENTINEL_PREFIX
from .row_runs import is_data_row_candidate
from .structural import (
    is_header_prefix,
    is_structural_table_bridge,
    is_structural_table_tail,
)

_MAX_HEADER_LOOKBACK = 4
_MAX_HEADER_GAP = 3
_MAX_STRUCTURAL_BRIDGE_GAP = 8
# A grown table is downgraded unless it shows at least this many numeric rows...
_MIN_DISCIPLINE_NUMERIC_ROWS = 2
# ...or this many shared numeric columns.
_MIN_DISCIPLINE_SHARED_COLUMNS = 2
# Confidence assigned to a span extended by a row-continuation or bridge signal.
_EXTENSION_CONFIDENCE = 0.75

Block = tuple[int, int, tuple[str, ...]]


class _BlockIndex:
    """Locate the blocks a decision covers without rescanning the whole list.
    Blocks are ascending and non-overlapping, so the covered slice is contiguous and found by binary search.
    """

    __slots__ = ("_blocks", "_cache", "_starts")

    def __init__(self, blocks: list[Block]) -> None:
        self._blocks = blocks
        self._starts = [start for start, _, _ in blocks]
        self._cache: dict[tuple[int, int], tuple[str, ...]] = {}

    def lines(self, start_line: int, end_line: int) -> tuple[str, ...]:
        key = (start_line, end_line)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        first = bisect.bisect_left(self._starts, start_line)
        collected: list[str] = []
        for start, end, block in self._blocks[first:]:
            if start >= end_line:
                break
            if end <= end_line:
                collected.extend(block)
        result = tuple(collected)
        self._cache[key] = result
        return result


def _block_lines(index: _BlockIndex, decision: SpanDecision) -> tuple[str, ...]:
    return index.lines(decision.start_line, decision.end_line)


def _validate_table_discipline(
    decision: SpanDecision,
    index: _BlockIndex,
) -> SpanDecision:
    """Validate table against protected overlaps and discipline gate."""
    block_lines = _block_lines(index, decision)
    if any(SENTINEL_PREFIX in line for line in block_lines):
        return SpanDecision(
            ACTION_PRESERVE,
            decision.start_line,
            decision.end_line,
            decision.confidence,
            decision.evidence + ("protected_table_overlap",),
            decision.trace,
        )
    features = _compute_features(block_lines)
    numeric_rows = len(getattr(features, "numeric_cell_rows", ()))
    shared_cols = getattr(features, "shared_numeric_columns", 0)
    if (
        numeric_rows >= _MIN_DISCIPLINE_NUMERIC_ROWS
        or shared_cols >= _MIN_DISCIPLINE_SHARED_COLUMNS
    ):
        return decision
    return SpanDecision(
        ACTION_PRESERVE,
        decision.start_line,
        decision.end_line,
        decision.confidence,
        decision.evidence + ("tag_discipline_downgrade",),
        decision.trace,
    )


def resolve_table_regions(
    decisions: list[SpanDecision],
    blocks: list[Block],
    policy: ReflowPolicy | None = None,
    max_blank_lines: int = 1,
) -> list[SpanDecision]:
    """Resolve and coalesce table boundaries in a single forward pass."""
    if not decisions:
        return []

    start_to_idx = {b[0]: i for i, b in enumerate(blocks)}
    n_blocks = len(blocks)
    index = _BlockIndex(blocks)

    resolved: list[SpanDecision] = []
    i = 0
    n = len(decisions)

    while i < n:
        decision = decisions[i]
        if decision.action != ACTION_TAG_AND_PRESERVE:
            resolved.append(decision)
            i += 1
            continue

        table_start_line = decision.start_line
        table_end_line = decision.end_line
        evidence = list(decision.evidence)
        confidence = decision.confidence

        cur_b_idx = start_to_idx.get(table_start_line)
        cur_lines = _block_lines(index, decision)
        features = _compute_features(cur_lines)

        if (
            features.numeric_cell_rows
            and cur_b_idx is not None
            and "repeated_row_geometry" not in decision.evidence
        ):
            absorbed_count = 0
            for back in range(1, min(_MAX_HEADER_LOOKBACK, cur_b_idx + 1)):
                cand_b_idx = cur_b_idx - back
                cand_start, cand_end, cand_lines = blocks[cand_b_idx]
                next_start = blocks[cand_b_idx + 1][0]
                if next_start - cand_end > _MAX_HEADER_GAP:
                    break
                if any(SENTINEL_PREFIX in line for line in cand_lines):
                    break
                if is_data_row_candidate(cand_lines):
                    break
                if is_header_prefix(cand_lines):
                    if (
                        resolved
                        and resolved[-1].start_line == cand_start
                        and resolved[-1].action in (ACTION_PRESERVE, ACTION_UNWRAP)
                    ):
                        popped = resolved.pop()
                        table_start_line = cand_start
                        confidence = min(confidence, popped.confidence)
                        absorbed_count += 1
                    else:
                        break
                else:
                    break
            if absorbed_count:
                evidence.append("expanded_table_header")

        curr_end_b_idx = start_to_idx.get(decision.end_line)
        if curr_end_b_idx is None:
            for b_i in range(cur_b_idx if cur_b_idx is not None else 0, n_blocks):
                if blocks[b_i][1] == table_end_line:
                    curr_end_b_idx = b_i + 1
                    break
            if curr_end_b_idx is None:
                curr_end_b_idx = (cur_b_idx + 1) if cur_b_idx is not None else i + 1

        next_decision_idx = i + 1
        active_lines = list(
            _block_lines(
                index,
                SpanDecision(
                    ACTION_TAG_AND_PRESERVE,
                    table_start_line,
                    table_end_line,
                    confidence,
                    (),
                    "",
                ),
            )
        )

        while next_decision_idx < n:
            next_d = decisions[next_decision_idx]

            if next_d.action == ACTION_TAG_AND_PRESERVE:
                if 0 <= next_d.start_line - table_end_line <= max_blank_lines:
                    table_end_line = next_d.end_line
                    confidence = min(confidence, next_d.confidence)
                    evidence.append("bridged_blank_line")
                    active_lines.extend(_block_lines(index, next_d))
                    next_decision_idx += 1
                    continue
                break

            cand_lines = _block_lines(index, next_d)

            if next_d.action != ACTION_UNWRAP and is_table_row_continuation(
                tuple(active_lines), cand_lines, policy
            ):
                table_end_line = next_d.end_line
                confidence = min(confidence, _EXTENSION_CONFIDENCE)
                evidence.append("extended_multiline_rows")
                active_lines.extend(cand_lines)
                next_decision_idx += 1
                continue

            stripped_cand = tuple(line.strip() for line in cand_lines if line.strip())
            if (
                stripped_cand
                and policy is not None
                and policy.is_page_boundary_line is not None
                and all(policy.is_page_boundary_line(line) for line in stripped_cand)
                and next_decision_idx + 1 < n
                and decisions[next_decision_idx + 1].action == ACTION_TAG_AND_PRESERVE
            ):
                following_d = decisions[next_decision_idx + 1]
                table_end_line = following_d.end_line
                confidence = min(confidence, following_d.confidence)
                evidence.append("bridged_page_marker")
                active_lines.extend(cand_lines)
                active_lines.extend(_block_lines(index, following_d))
                next_decision_idx += 2
                continue

            bridge_lines: list[str] = []
            look_idx = next_decision_idx
            while look_idx < n and decisions[look_idx].action in (
                ACTION_PRESERVE,
                ACTION_UNWRAP,
            ):
                bridge_lines.extend(_block_lines(index, decisions[look_idx]))
                look_idx += 1

            if (
                look_idx < n
                and decisions[look_idx].action == ACTION_TAG_AND_PRESERVE
                and bridge_lines
            ):
                following_d = decisions[look_idx]
                if (
                    is_structural_table_bridge(
                        tuple(bridge_lines),
                        is_bridge_line=(
                            policy.is_table_bridge_line if policy is not None else None
                        ),
                    )
                    and following_d.start_line - table_end_line
                    <= _MAX_STRUCTURAL_BRIDGE_GAP
                ):
                    table_end_line = following_d.end_line
                    confidence = min(
                        confidence, following_d.confidence, _EXTENSION_CONFIDENCE
                    )
                    evidence.append("bridged_structural_section")
                    active_lines.extend(bridge_lines)
                    active_lines.extend(_block_lines(index, following_d))
                    next_decision_idx = look_idx + 1

                    if next_decision_idx < n:
                        tail_d = decisions[next_decision_idx]
                        tail_lines = _block_lines(index, tail_d)
                        if is_structural_table_tail(
                            tail_lines,
                            is_tail_line=(
                                policy.is_table_tail_line
                                if policy is not None
                                else None
                            ),
                        ):
                            table_end_line = tail_d.end_line
                            evidence.append("included_table_tail")
                            active_lines.extend(tail_lines)
                            next_decision_idx += 1
                    continue

            if next_d.action != ACTION_UNWRAP:
                cand_features = _compute_features(cand_lines)
                if cand_features.numeric_cell_rows:
                    break

                if (
                    next_decision_idx + 1 < n
                    and decisions[next_decision_idx + 1].action != ACTION_UNWRAP
                ):
                    lookahead_lines = _block_lines(
                        index, decisions[next_decision_idx + 1]
                    )
                    if is_table_row_continuation(
                        tuple(active_lines), lookahead_lines, policy
                    ):
                        table_end_line = decisions[next_decision_idx + 1].end_line
                        confidence = min(confidence, _EXTENSION_CONFIDENCE)
                        evidence.append("extended_multiline_rows")
                        active_lines.extend(cand_lines)
                        active_lines.extend(lookahead_lines)
                        next_decision_idx += 2
                        if RE_SEPARATOR_LINE.fullmatch(
                            lookahead_lines[-1].strip() if lookahead_lines else ""
                        ):
                            break
                        continue

            break

        candidate_final = SpanDecision(
            ACTION_TAG_AND_PRESERVE,
            table_start_line,
            table_end_line,
            confidence,
            tuple(evidence),
            decision.trace,
        )
        final_decision = _validate_table_discipline(candidate_final, index)
        resolved.append(final_decision)
        i = next_decision_idx

    return resolved


__all__ = ["resolve_table_regions"]
