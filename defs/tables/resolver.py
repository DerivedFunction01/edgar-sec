"""Single-pass table region resolver for generic ASCII reflow."""

from __future__ import annotations

from defs.tables.protection import _SENTINEL_PREFIX
from defs.tables.structural import (
    is_header_prefix,
    is_structural_table_bridge,
    is_structural_table_tail,
)
from defs.tables.table_policy import (
    _block_lines,
    is_table_row_continuation,
)
from defs.text.patterns import RE_SEPARATOR_LINE
from defs.text.reflow.features import _compute_features
from defs.text.reflow.types import (
    ACTION_PRESERVE,
    ACTION_TAG_AND_PRESERVE,
    ACTION_UNWRAP,
    ReflowPolicy,
    SpanDecision,
)


def _validate_table_discipline(
    decision: SpanDecision,
    blocks: list[tuple[int, int, tuple[str, ...]]],
) -> SpanDecision:
    """Validate table against protected overlaps and discipline gate."""
    block_lines = _block_lines(blocks, decision)
    if any(_SENTINEL_PREFIX in line for line in block_lines):
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
    if numeric_rows >= 2 or shared_cols >= 2:
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
    blocks: list[tuple[int, int, tuple[str, ...]]],
    policy: ReflowPolicy | None = None,
    max_blank_lines: int = 1,
) -> list[SpanDecision]:
    """Resolve and coalesce table boundaries in a single forward pass."""
    if not decisions:
        return []

    # Map block start_line to index for O(1) lookups
    start_to_idx = {b[0]: i for i, b in enumerate(blocks)}
    n_blocks = len(blocks)

    def block_lines_at(idx: int) -> tuple[str, ...]:
        return blocks[idx][2] if 0 <= idx < n_blocks else ()

    resolved: list[SpanDecision] = []
    i = 0
    n = len(decisions)

    while i < n:
        decision = decisions[i]
        if decision.action != ACTION_TAG_AND_PRESERVE:
            resolved.append(decision)
            i += 1
            continue

        # Found a table seed: decision at index i
        table_start_line = decision.start_line
        table_end_line = decision.end_line
        evidence = list(decision.evidence)
        confidence = decision.confidence

        cur_b_idx = start_to_idx.get(table_start_line)
        cur_lines = _block_lines(blocks, decision)
        features = _compute_features(cur_lines)

        # Step 1: Backward Expand Headers (if this seed has numeric cells)
        if features.numeric_cell_rows and cur_b_idx is not None:
            absorbed_count = 0
            for back in range(1, min(4, cur_b_idx + 1)):
                cand_b_idx = cur_b_idx - back
                cand_start, cand_end, cand_lines = blocks[cand_b_idx]
                # Check distance
                next_start = blocks[cand_b_idx + 1][0]
                if next_start - cand_end > 3:
                    break
                if any(_SENTINEL_PREFIX in line for line in cand_lines):
                    break
                # Must be a header prefix
                if is_header_prefix(cand_lines):
                    # Check whether candidate was emitted as PRESERVE or UNWRAP
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

        # Step 2: Forward Sweep for Continuations, Bridges, Adjacent Tables, and Tails
        curr_end_b_idx = start_to_idx.get(decision.end_line)
        # Find block index covering or adjacent to table_end_line
        if curr_end_b_idx is None:
            # find block with end == table_end_line
            for b_i in range(cur_b_idx if cur_b_idx is not None else 0, n_blocks):
                if blocks[b_i][1] == table_end_line:
                    curr_end_b_idx = b_i + 1
                    break
            if curr_end_b_idx is None:
                curr_end_b_idx = (cur_b_idx + 1) if cur_b_idx is not None else i + 1

        next_decision_idx = i + 1
        active_lines = list(
            _block_lines(
                blocks,
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

        # Greedy forward extension & bridge loop
        while next_decision_idx < n:
            next_d = decisions[next_decision_idx]

            # Case A: Next is already ACTION_TAG_AND_PRESERVE
            if next_d.action == ACTION_TAG_AND_PRESERVE:
                # Blank lines gap check
                if 0 <= next_d.start_line - table_end_line <= max_blank_lines:
                    table_end_line = next_d.end_line
                    confidence = min(confidence, next_d.confidence)
                    evidence.append("bridged_blank_line")
                    active_lines.extend(_block_lines(blocks, next_d))
                    next_decision_idx += 1
                    continue
                break

            # Case B: Next is PRESERVE or UNWRAP (potential bridge, page marker, or row continuation)
            cand_lines = _block_lines(blocks, next_d)

            # 1. Check if next is a continuation row (only for non-UNWRAP blocks)
            if next_d.action != ACTION_UNWRAP and is_table_row_continuation(
                tuple(active_lines), cand_lines, policy
            ):
                # Extend row
                table_end_line = next_d.end_line
                confidence = min(confidence, 0.75)
                evidence.append("extended_multiline_rows")
                active_lines.extend(cand_lines)
                next_decision_idx += 1
                continue

            # 2. Check if next spans are page markers leading to another table
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
                active_lines.extend(_block_lines(blocks, following_d))
                next_decision_idx += 2
                continue

            # 3. Check if next spans form a structural table bridge leading to another table
            bridge_lines: list[str] = []
            look_idx = next_decision_idx
            while look_idx < n and decisions[look_idx].action in (
                ACTION_PRESERVE,
                ACTION_UNWRAP,
            ):
                bridge_lines.extend(_block_lines(blocks, decisions[look_idx]))
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
                    and following_d.start_line - table_end_line <= 8
                ):
                    table_end_line = following_d.end_line
                    confidence = min(confidence, following_d.confidence, 0.75)
                    evidence.append("bridged_structural_section")
                    active_lines.extend(bridge_lines)
                    active_lines.extend(_block_lines(blocks, following_d))
                    next_decision_idx = look_idx + 1

                    # Optional tail after structural bridge
                    if next_decision_idx < n:
                        tail_d = decisions[next_decision_idx]
                        tail_lines = _block_lines(blocks, tail_d)
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

            # 4. Check if candidate block has numeric continuation with lookahead (only for non-UNWRAP blocks)
            if next_d.action != ACTION_UNWRAP:
                cand_features = _compute_features(cand_lines)
                if cand_features.numeric_cell_rows:
                    # Numeric cells but not continuation -> stop
                    break

                # Non-numeric block: check if next-next is a continuation
                if (
                    next_decision_idx + 1 < n
                    and decisions[next_decision_idx + 1].action != ACTION_UNWRAP
                ):
                    lookahead_lines = _block_lines(
                        blocks, decisions[next_decision_idx + 1]
                    )
                    if is_table_row_continuation(
                        tuple(active_lines), lookahead_lines, policy
                    ):
                        table_end_line = decisions[next_decision_idx + 1].end_line
                        confidence = min(confidence, 0.75)
                        evidence.append("extended_multiline_rows")
                        active_lines.extend(cand_lines)
                        active_lines.extend(lookahead_lines)
                        next_decision_idx += 2
                        if RE_SEPARATOR_LINE.fullmatch(
                            lookahead_lines[-1].strip() if lookahead_lines else ""
                        ):
                            break
                        continue

            # No further forward matches
            break

        # Step 3: Validate Table Discipline on Final Span
        candidate_final = SpanDecision(
            ACTION_TAG_AND_PRESERVE,
            table_start_line,
            table_end_line,
            confidence,
            tuple(evidence),
            decision.trace,
        )
        final_decision = _validate_table_discipline(candidate_final, blocks)
        resolved.append(final_decision)
        i = next_decision_idx

    return resolved


__all__ = ["resolve_table_regions"]
