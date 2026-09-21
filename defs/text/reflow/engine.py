"""Conservative ASCII prose reflow and untagged-table tagging engine."""

from __future__ import annotations

from defs.tables.protection import (
    _SENTINEL_PREFIX,
    ensure_table_tag_boundaries,
    mask_tagged_tables,
    restore_tagged_tables,
)
from defs.tables.table_policy import (
    expand_table_headers,
    extend_multiline_table_rows,
    is_tableish_block,
    merge_bridged_tables,
    merge_structural_table_regions,
    split_structural_table_intro,
    tag_discipline_gate,
    unify_table_prose,
)
from defs.text.patterns import RE_SEPARATOR_LINE
from defs.text.signatures import mask_signature_regions, restore_signature_regions
from defs.text.tokens import is_bullet_line

from .classifier import _decide
from .features import _compute_features, _numeric_cell_starts
from .types import (
    ACTION_PRESERVE,
    ACTION_TAG_AND_PRESERVE,
    ACTION_UNWRAP,
    ReflowPolicy,
    ReflowResult,
    SpanDecision,
)


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
        and getattr(features, "alpha_density", 0.0) >= 0.55
        and getattr(features, "any_lowercase", False)
        and not getattr(features, "has_separator", False)
        and len(getattr(features, "numeric_cell_rows", ())) < 3
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
    masked_body_start_line = body_start_line
    for span in spans:
        span_start_line = text.count("\n", 0, span.start)
        span_newline_count = span.text.count("\n")
        span_end_line = span_start_line + span_newline_count
        if span_end_line <= body_start_line:
            masked_body_start_line -= span_newline_count
        elif span_start_line < body_start_line:
            masked_body_start_line -= body_start_line - span_start_line
    masked_body_start_line = max(0, masked_body_start_line)

    active_policy = policy or ReflowPolicy()
    lines = masked.split("\n")
    blocks = _segment(lines, policy=active_policy)
    per_block: list[tuple[tuple[int, int, tuple[str, ...]], SpanDecision]] = []
    for start, end, block_lines in blocks:
        if end <= masked_body_start_line and not active_policy.unwrap_pre_body_prose:
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
        base_decision = _decide(features, len(block_lines), has_masked)
        if _is_bullet_prose_block(block_lines, features, active_policy):
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
        ):
            decision = SpanDecision(
                ACTION_TAG_AND_PRESERVE,
                0,
                len(block_lines),
                0.8,
                ("inferred_table_layout",),
                "table_continuity",
            )
        elif active_policy.unwrap_pre_body_prose and any(
            end <= masked_body_start_line
            and active_policy.is_structural_line is not None
            and active_policy.is_structural_line(line)
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
            active_policy.relax_prose_layout_gaps
            and features.alpha_density >= 0.55
            and features.any_lowercase
            and not features.has_structural
            and not features.has_tab
            and not features.has_separator
            and not features.has_dot_leader
            and not features.has_signature
            and features.shared_numeric_columns == 0
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
        if end <= masked_body_start_line and decision.action == ACTION_TAG_AND_PRESERVE:
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

    decisions = expand_table_headers([decision for _, decision in per_block], blocks)
    decisions = extend_multiline_table_rows(decisions, blocks, policy=active_policy)
    decisions = merge_bridged_tables(decisions, blocks=blocks, policy=active_policy)
    decisions = merge_structural_table_regions(decisions, blocks, policy=active_policy)
    decisions = tag_discipline_gate(decisions, blocks)
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
            if "inferred_table_layout" in decision.evidence:
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
                if (
                    decision.action == ACTION_TAG_AND_PRESERVE
                    and "inferred_table_layout" in decision.evidence
                ):
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


__all__ = [
    "reflow_ascii",
]
