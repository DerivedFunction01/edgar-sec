"""Conservative ASCII prose reflow and untagged-table tagging.
The bias is asymmetric: a missed unwrap leaves prose hard-wrapped and recoverable, a collapsed table corrupts financial data. Ambiguous blocks resolve to preserve, as does a block that still looks like a table once the resolver has absorbed all it may.
"""

from __future__ import annotations

import bisect

from edgar_sec.engine.document.page_markers.signatures import (
    mask_signature_regions,
    restore_signature_regions,
)
from edgar_sec.engine.tables.policy.intro import (
    is_tableish_block,
    split_structural_table_intro,
    unify_table_prose,
)
from edgar_sec.engine.tables.protection.tags import (
    SENTINEL_PREFIX,
    TableSpan,
    ensure_table_tag_boundaries,
    mask_tagged_tables,
    restore_tagged_tables,
)
from edgar_sec.engine.tables.resolver import resolve_table_regions
from edgar_sec.engine.tables.row_runs import (
    find_table_row_runs,
    is_table_row_run_bridge,
)
from edgar_sec.foundation.text.patterns import RE_SEPARATOR_LINE
from edgar_sec.foundation.text.tokens import is_bullet_line

from ..features.context import BlockContext
from ..features.geometry import (
    _Features,
    _numeric_cell_starts,
    fast_detect_prose_measure,
)
from ..rules.cascades import _decide, decide_block
from ..types import (
    ACTION_PRESERVE,
    ACTION_TAG_AND_PRESERVE,
    ACTION_UNWRAP,
    ReflowPolicy,
    ReflowResult,
    SpanDecision,
)

# Alpha density, a lowercase letter, and no separator or dense numeric grid together mean a
# bullet's wrapped continuation is prose.
_BULLET_PROSE_ALPHA_DENSITY = 0.55
_BULLET_PROSE_MAX_NUMERIC_ROWS = 3
_RELAXED_PROSE_ALPHA_DENSITY = 0.55
_PROSE_ALIGNMENT_EVIDENCE = frozenset(
    ("linguistic_numeric_prose", "prose_dominant_numeric_alignment")
)


_ROW_RUN_BLOCKED_EVIDENCE = frozenset(
    (
        "pre_body_region",
        "protected_tagged_table",
        "structural_marker",
        "internal_tab",
        "signature_shape",
        "front_matter_form_layout",
    )
)


def _eligible_row_block_indices(
    per_block: list[tuple[tuple[int, int, tuple[str, ...]], SpanDecision]],
    policy: ReflowPolicy,
    body_start_line: int,
) -> set[int]:
    """Collect the blocks a row run may grow from, cheapest test first.
    Order is free to change: every condition is independent, and only the sentinel and policy scans touch every line.
    """
    predicates = tuple(
        predicate
        for predicate in (
            policy.is_page_boundary_line,
            policy.is_structural_line,
            policy.is_checkbox_answer_line,
        )
        if predicate is not None
    )
    eligible: set[int] = set()
    for index, ((_, end, block_lines), decision) in enumerate(per_block):
        if decision.action not in (
            ACTION_PRESERVE,
            ACTION_UNWRAP,
            ACTION_TAG_AND_PRESERVE,
        ):
            continue
        if end <= body_start_line:
            continue
        if _ROW_RUN_BLOCKED_EVIDENCE.intersection(decision.evidence):
            continue
        if any(SENTINEL_PREFIX in line for line in block_lines):
            continue
        if any(
            predicate(line.strip()) for line in block_lines for predicate in predicates
        ):
            continue
        eligible.add(index)
    return eligible


def _overlap_window(
    decisions: list[SpanDecision],
    start_line: int,
    end_line: int,
) -> tuple[int, int]:
    """Return the slice of ascending decisions that overlaps ``[start, end)``.
    The start list is rebuilt per call: carrying it alongside would trade a sorted list for an invariant that can silently desync.
    """
    last = bisect.bisect_left([decision.start_line for decision in decisions], end_line)
    first = last
    while first > 0 and decisions[first - 1].end_line > start_line:
        first -= 1
    return first, last


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


def _coalesce_confirmed_row_runs(
    decisions: list[SpanDecision],
    blocks: list[tuple[int, int, tuple[str, ...]]],
    policy: ReflowPolicy,
) -> list[SpanDecision]:
    merged: list[SpanDecision] = []
    index = 0
    block_starts = [start for start, _, _ in blocks]
    while index < len(decisions):
        current = decisions[index]
        if (
            current.action != ACTION_TAG_AND_PRESERVE
            or "repeated_row_geometry" not in current.evidence
        ):
            merged.append(current)
            index += 1
            continue

        next_index = index + 1
        while next_index < len(decisions):
            following_index = next_index
            while (
                following_index < len(decisions)
                and decisions[following_index].action != ACTION_TAG_AND_PRESERVE
            ):
                following_index += 1
            if following_index >= len(decisions):
                break
            following = decisions[following_index]
            gap = following.start_line - current.end_line
            if gap < 0 or gap > 8:
                break
            first_bridge = bisect.bisect_left(block_starts, current.end_line)
            last_bridge = bisect.bisect_left(block_starts, following.start_line)
            bridge_lines = tuple(
                line
                for start, end, lines in blocks[first_bridge:last_bridge]
                for line in lines
            )
            if not is_table_row_run_bridge(
                bridge_lines,
                is_page_boundary_line=policy.is_page_boundary_line,
                is_table_bridge_line=policy.is_table_bridge_line,
            ):
                break

            evidence = tuple(
                dict.fromkeys(
                    (*current.evidence, "bounded_row_run_bridge", *following.evidence)
                )
            )
            current = SpanDecision(
                ACTION_TAG_AND_PRESERVE,
                current.start_line,
                following.end_line,
                min(current.confidence, following.confidence),
                evidence,
                "table_row_run",
            )
            next_index = following_index + 1

        merged.append(current)
        index = next_index
    return merged


def _segment(
    lines: list[str],
    *,
    policy: ReflowPolicy,
) -> list[tuple[int, int, tuple[str, ...]]]:
    """Group into blocks of consecutive non-blank lines (blank lines excluded)."""
    blocks: list[tuple[int, int, tuple[str, ...]]] = []
    current: list[str] = []
    start = 0
    for index, line in enumerate(lines):
        if line.strip():
            if current and RE_SEPARATOR_LINE.fullmatch(current[-1].strip()):
                has_numeric_tail = bool(_numeric_cell_starts(line))
                if not has_numeric_tail and line.lstrip()[:1].isalpha():
                    blocks.append((start, index, tuple(current)))
                    current = []
            starts_block = (
                bool(policy.is_structural_line and policy.is_structural_line(line))
                or (policy.split_bullet_items and is_bullet_line(line))
                or bool(
                    policy.is_checkbox_answer_line
                    and policy.is_checkbox_answer_line(line)
                )
            )
            if starts_block and current:
                blocks.append((start, index, tuple(current)))
                current = []
            if not current:
                start = index
            current.append(line)
        elif current:
            blocks.append((start, index, tuple(current)))
            current = []
    if current:
        blocks.append((start, len(lines), tuple(current)))
    return blocks


def _is_bullet_prose_block(
    block_lines: tuple[str, ...], features: object, policy: ReflowPolicy
) -> bool:
    return bool(
        policy.unwrap_bullet_continuations
        and len(block_lines) > 1
        and is_bullet_line(block_lines[0])
        and getattr(features, "alpha_density", 0.0) >= _BULLET_PROSE_ALPHA_DENSITY
        and getattr(features, "any_lowercase", False)
        and not getattr(features, "has_separator", False)
        and len(getattr(features, "numeric_cell_rows", ()))
        < _BULLET_PROSE_MAX_NUMERIC_ROWS
    )


def _merge_adjacent_prose_decisions(
    decisions: list[SpanDecision],
) -> list[SpanDecision]:
    """Join contiguous prose blocks split by removable layout boundaries."""
    merged: list[SpanDecision] = []
    prose_traces = {"fast_prose", "front_matter_prose"}
    for decision in decisions:
        if (
            merged
            and decision.action == ACTION_UNWRAP
            and merged[-1].action == ACTION_UNWRAP
            and decision.start_line - merged[-1].end_line <= 1
            and merged[-1].trace in prose_traces
            and decision.trace in prose_traces
            and "bullet_prose_continuation" not in merged[-1].evidence
            and "bullet_prose_continuation" not in decision.evidence
        ):
            previous = merged[-1]
            evidence = tuple(dict.fromkeys((*previous.evidence, *decision.evidence)))
            merged[-1] = SpanDecision(
                ACTION_UNWRAP,
                previous.start_line,
                decision.end_line,
                min(previous.confidence, decision.confidence),
                evidence,
                previous.trace,
            )
        else:
            merged.append(decision)
    return merged


def _classify_block(
    block_lines: tuple[str, ...],
    *,
    start_line: int,
    end_line: int,
    body_start_line: int,
    page_context: bool,
    policy: ReflowPolicy,
    target_width: int = 80,
    features: _Features | None = None,
) -> SpanDecision:
    """Return the production first-pass decision for one segmented block."""
    if end_line <= body_start_line and not policy.unwrap_pre_body_prose:
        return SpanDecision(
            ACTION_PRESERVE,
            start_line,
            end_line,
            1.0,
            ("pre_body_region",),
            "fast_noop",
        )

    has_masked = any(SENTINEL_PREFIX in line for line in block_lines)
    ctx = (
        BlockContext(block_lines, policy, target_width=target_width)
        if features is None
        else features
    )
    base_decision = _decide(ctx, len(block_lines), has_masked)
    features = ctx

    if _is_bullet_prose_block(block_lines, features, policy):
        decision = SpanDecision(
            ACTION_UNWRAP,
            0,
            len(block_lines),
            0.8,
            ("bullet_prose_continuation",),
            "bullet_reflow",
        )
    elif (
        is_tableish_block(features)
        and base_decision.action != ACTION_TAG_AND_PRESERVE
        and not _PROSE_ALIGNMENT_EVIDENCE.intersection(base_decision.evidence)
    ):
        target_action = (
            ACTION_TAG_AND_PRESERVE if policy.tag_untagged_tables else ACTION_PRESERVE
        )
        decision = SpanDecision(
            target_action,
            0,
            len(block_lines),
            0.8,
            ("inferred_table_layout",),
            "table_continuity",
        )
    elif policy.unwrap_pre_body_prose and any(
        end_line <= body_start_line
        and policy.is_structural_line is not None
        and policy.is_structural_line(line)
        for line in block_lines
    ):
        decision = SpanDecision(
            ACTION_PRESERVE,
            0,
            len(block_lines),
            1.0,
            ("front_matter_form_layout",),
            "hard_preserve",
        )
    elif (
        policy.relax_prose_layout_gaps
        and features.alpha_density >= _RELAXED_PROSE_ALPHA_DENSITY
        and features.any_lowercase
        and not features.has_structural
        and not features.has_tab
        and not features.has_separator
        and not features.has_dot_leader
        and not features.has_signature
        and (
            features.shared_numeric_columns == 0
            or getattr(features, "is_justified_prose", False)
        )
        and not getattr(features, "is_width_overflow", False)
    ):
        decision = SpanDecision(
            ACTION_UNWRAP,
            0,
            len(block_lines),
            0.65,
            ("relaxed_prose_layout",),
            "front_matter_prose",
        )
    else:
        decision = base_decision

    if end_line <= body_start_line and decision.action == ACTION_TAG_AND_PRESERVE:
        decision = SpanDecision(
            ACTION_PRESERVE,
            0,
            len(block_lines),
            1.0,
            ("front_matter_form_layout",),
            "hard_preserve",
        )
    if page_context and decision.action == ACTION_UNWRAP:
        decision = SpanDecision(
            decision.action,
            decision.start_line,
            decision.end_line,
            decision.confidence,
            decision.evidence + ("page_boundary_context",),
            decision.trace,
        )
    return SpanDecision(
        decision.action,
        start_line,
        end_line,
        decision.confidence,
        decision.evidence,
        decision.trace,
    )


def _masked_body_start(
    text: str,
    spans: tuple[TableSpan, ...],
    body_start_line: int,
) -> int:
    """Project the body boundary from source lines into the masked frame.
    Newlines inside a masked span are gone from the line sequence, so the boundary moves.
    """
    masked_body_start_line = body_start_line
    for span in spans:
        span_start_line = text.count("\n", 0, span.start)
        span_newline_count = span.text.count("\n")
        span_end_line = span_start_line + span_newline_count
        if span_end_line <= body_start_line:
            masked_body_start_line -= span_newline_count
        elif span_start_line < body_start_line:
            masked_body_start_line -= body_start_line - span_start_line
    return max(0, masked_body_start_line)


def reflow_ascii(
    text: str,
    *,
    body_start_line: int | None = None,
    page_analysis: object | None = None,
    policy: ReflowPolicy | None = None,
) -> ReflowResult:
    """Run the conservative gate cascade over plain-text filing content."""
    if not text or "\n" not in text or body_start_line is None:
        return ReflowResult(text)

    page_context = bool(getattr(page_analysis, "page_number_runs", ()))
    masked, spans = mask_tagged_tables(text)
    masked, signature_regions = mask_signature_regions(masked)
    masked_body_start_line = _masked_body_start(text, spans, body_start_line)

    active_policy = policy or ReflowPolicy()

    lines = masked.split("\n")
    target_width = fast_detect_prose_measure(
        lines, body_start_line=masked_body_start_line
    )
    blocks = _segment(lines, policy=active_policy)
    per_block: list[tuple[tuple[int, int, tuple[str, ...]], SpanDecision]] = []
    for start, end, block_lines in blocks:
        decision = _classify_block(
            block_lines,
            start_line=start,
            end_line=end,
            body_start_line=masked_body_start_line,
            page_context=page_context,
            policy=active_policy,
            target_width=target_width,
        )
        per_block.append(
            (
                (start, end, block_lines),
                decision,
            )
        )

    if active_policy.tag_untagged_tables:
        row_block_indices = _eligible_row_block_indices(
            per_block, active_policy, masked_body_start_line
        )
        row_runs = find_table_row_runs(blocks, row_block_indices)
        decisions = resolve_table_regions(
            [decision for _, decision in per_block], blocks, policy=active_policy
        )
        decisions.sort(key=lambda decision: decision.start_line)
        for run in row_runs:
            first, last = _overlap_window(decisions, run.start_line, run.end_line)
            overlaps = decisions[first:last]
            tag_overlaps = [
                decision
                for decision in overlaps
                if decision.action == ACTION_TAG_AND_PRESERVE
            ]
            if any(
                decision.start_line <= run.start_line
                and run.end_line <= decision.end_line
                for decision in tag_overlaps
            ):
                continue
            span_start = min(
                (run.start_line, *(decision.start_line for decision in tag_overlaps))
            )
            span_end = max(
                (run.end_line, *(decision.end_line for decision in tag_overlaps))
            )
            if any(
                decision.action in (ACTION_PRESERVE, ACTION_UNWRAP)
                and not (
                    span_start <= decision.start_line and decision.end_line <= span_end
                )
                for decision in overlaps
            ):
                continue

            run_context = BlockContext(
                tuple(lines[run.start_line : run.end_line]),
                active_policy,
                target_width=target_width,
            )
            run_classification = decide_block(
                run_context, line_count=run_context.line_count
            )
            if run_classification.trace == "preserve_linguistic_numeric_alignment":
                continue

            row_decision = SpanDecision(
                ACTION_TAG_AND_PRESERVE,
                span_start,
                span_end,
                0.8,
                (
                    "repeated_row_geometry",
                    *(
                        run_classification.evidence
                        if run_classification.action == ACTION_TAG_AND_PRESERVE
                        else ()
                    ),
                    "repeated_numeric_field",
                    "minimum_row_run",
                ),
                "table_row_run",
            )
            # Every span this run supersedes overlaps it, so replacements stay inside the window: splice the
            # window rather than rebuilding the whole list per run.
            window = [
                decision
                for decision in overlaps
                if not (
                    decision.action
                    in (ACTION_PRESERVE, ACTION_UNWRAP, ACTION_TAG_AND_PRESERVE)
                    and span_start <= decision.start_line
                    and decision.end_line <= span_end
                )
            ]
            window.append(row_decision)
            window.sort(key=lambda decision: decision.start_line)
            decisions[first:last] = window
        if row_runs:
            decisions = _coalesce_confirmed_row_runs(decisions, blocks, active_policy)
    else:
        decisions = [
            SpanDecision(
                ACTION_PRESERVE,
                d.start_line,
                d.end_line,
                d.confidence,
                d.evidence,
                d.trace,
            )
            if d.action == ACTION_TAG_AND_PRESERVE
            else d
            for _, d in per_block
        ]
    decisions = _merge_adjacent_prose_decisions(decisions)
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

        unified = unify_table_prose(
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
            table_lines = tuple(merged_lines)
            if decision.action == ACTION_TAG_AND_PRESERVE:
                splitter = (
                    active_policy.split_table_intro or split_structural_table_intro
                )
                intro, table_lines = splitter(table_lines)
                if intro:
                    rendered.append(_render_block(ACTION_UNWRAP, intro))
            rendered.append(_render_block(decision.action, table_lines))
        else:
            for _, _, block_lines in group:
                table_lines = block_lines
                if decision.action == ACTION_TAG_AND_PRESERVE:
                    splitter = (
                        active_policy.split_table_intro or split_structural_table_intro
                    )
                    intro, table_lines = splitter(table_lines)
                    if intro:
                        rendered.append(_render_block(ACTION_UNWRAP, intro))
                rendered.append(_render_block(decision.action, table_lines))
        cursor = decision.end_line
        decision_index += 1

    if cursor < len(lines):
        rendered.append("\n".join(lines[cursor:]))

    result_text = restore_signature_regions("\n".join(rendered), signature_regions)
    result_text = restore_tagged_tables(result_text, spans)
    result_text = ensure_table_tag_boundaries(result_text)
    return ReflowResult(
        result_text,
        tuple(decisions),
        spans,
        signature_regions,
    )


__all__ = ["reflow_ascii"]
