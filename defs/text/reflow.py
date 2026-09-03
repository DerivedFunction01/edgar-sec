"""Conservative ASCII prose reflow and untagged-table tagging.

This is the Stage-4 span/action engine for plain-text (non-HTML) filings. It
classifies each blank-line-delimited block and renders the canonical output
from exact decisions:

- ``UNWRAP``: join ordinary hard-wrapped prose lines with single spaces.
- ``PRESERVE``: emit the original span unchanged, no tags.
- ``TAG_AND_PRESERVE``: emit the original span unchanged between uppercase
  ``<TABLE>``/``</TABLE>`` markers.

Safety bias is deliberate: a missed unwrap leaves prose hard-wrapped, but a
collapsed table corrupts financial data. Ambiguous blocks therefore always
resolve to ``PRESERVE``. Existing tagged ``<TABLE>`` blocks are masked before
analysis via ``defs.tables.protection`` and restored byte-for-byte; they are
never reclassified or reflowed.

All operations are deterministic and line-based. Decisions carry half-open
line ranges in the coordinate frame of the text passed in.
"""

from __future__ import annotations

from dataclasses import dataclass

from defs.tables.numeric_cells import NUMERIC_CELL_RE
from defs.tables.protection import (
    TableSpan,
    mask_tagged_tables,
    restore_tagged_tables,
)

from .patterns import (
    RE_COLUMN_GAP,
    RE_DOT_LEADER,
    RE_PAGE_NUMBER_SUFFIX,
    RE_SEPARATOR_RUN,
    RE_SIGNATURE_LABEL_LINE,
    RE_STRUCTURAL_SGML,
)

__all__ = [
    "ACTION_PRESERVE",
    "ACTION_TAG_AND_PRESERVE",
    "ACTION_UNWRAP",
    "ReflowResult",
    "SpanDecision",
    "reflow_ascii",
]

ACTION_UNWRAP = "unwrap"
ACTION_PRESERVE = "preserve"
ACTION_TAG_AND_PRESERVE = "tag_and_preserve"

_MIN_PROSE_ALPHA_DENSITY = 0.55


@dataclass(frozen=True, slots=True)
class SpanDecision:
    """One block-level action over a half-open line range."""

    action: str
    start_line: int
    end_line: int
    confidence: float
    evidence: tuple[str, ...] = ()
    trace: str = ""


@dataclass(frozen=True, slots=True)
class ReflowResult:
    """Reflowed text plus the per-block decision trace."""

    text: str
    decisions: tuple[SpanDecision, ...] = ()
    protected_tables: tuple[TableSpan, ...] = ()


@dataclass(frozen=True, slots=True)
class _Features:
    non_blank: int
    has_structural: bool
    has_tab: bool
    has_separator: bool
    has_dot_leader: bool
    has_signature: bool
    max_gap: int
    gap_start_rows: tuple[tuple[int, ...], ...]
    numeric_cell_rows: int
    alpha_density: float
    any_lowercase: bool


def _line_gap_starts(line: str) -> tuple[int, ...]:
    """Positions of internal whitespace runs that separate layout columns.

    Leading indentation is not a gap: indented prose and list items are
    eligible for unwrapping, so gap detection starts after the first
    content character.
    """
    stripped_end = len(line.rstrip())
    content_start = len(line) - len(line.lstrip())
    starts: list[int] = []
    for match in RE_COLUMN_GAP.finditer(line[:stripped_end]):
        if match.start() < content_start:
            continue
        if len(match.group()) >= 3:
            starts.append(match.start())
    return tuple(starts)


def _numeric_cell_starts(line: str) -> tuple[int, ...]:
    """Positions where a numeric/currency cell begins right after a gap."""
    stripped_end = len(line.rstrip())
    content_start = len(line) - len(line.lstrip())
    starts: list[int] = []
    for match in RE_COLUMN_GAP.finditer(line[:stripped_end]):
        if match.start() < content_start:
            continue
        tail = line[match.end() :].strip().split()
        if tail and NUMERIC_CELL_RE.match(tail[0]):
            starts.append(match.end())
    return tuple(starts)


def _shared_columns(
    cell_rows: tuple[tuple[int, ...], ...],
    *,
    min_rows: int,
    tolerance: int = 1,
) -> int:
    """Count columns covered by at least ``min_rows`` rows within tolerance."""
    if len(cell_rows) < min_rows:
        return 0
    counted: list[int] = []
    shared = 0
    for anchor in sorted({p for row in cell_rows for p in row}):
        lo, hi = anchor - tolerance, anchor + tolerance
        covering = sum(1 for row in cell_rows if any(lo <= p <= hi for p in row))
        if covering >= min_rows and not any(
            counted_col - tolerance <= anchor <= counted_col + tolerance
            for counted_col in counted
        ):
            shared += 1
            counted.append(anchor)
    return shared


def _compute_features(lines: tuple[str, ...]) -> _Features:
    non_blank = 0
    has_structural = has_tab = has_separator = False
    has_dot_leader = has_signature = False
    max_gap = 0
    gap_start_rows: list[tuple[int, ...]] = []
    numeric_cell_rows: list[tuple[int, ...]] = []
    alpha_chars = 0
    total_chars = 0
    any_lowercase = False

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        non_blank += 1
        if RE_STRUCTURAL_SGML.search(stripped):
            has_structural = True
        if "\t" in line:
            has_tab = True
        if RE_DOT_LEADER.search(stripped) and RE_PAGE_NUMBER_SUFFIX.search(stripped):
            has_dot_leader = True
        if RE_SIGNATURE_LABEL_LINE.match(line):
            has_signature = True
        if RE_SEPARATOR_RUN.search(stripped):
            has_separator = True
        if any(ch.islower() for ch in stripped):
            any_lowercase = True

        content_start = len(line) - len(line.lstrip())
        for match in RE_COLUMN_GAP.finditer(line[: len(line.rstrip())]):
            if match.start() < content_start:
                continue
            max_gap = max(max_gap, len(match.group()))
        gaps = _line_gap_starts(line)
        if gaps:
            gap_start_rows.append(gaps)
        cells = _numeric_cell_starts(line)
        if cells:
            numeric_cell_rows.append(cells)

        letters = sum(ch.isalpha() for ch in stripped)
        alpha_chars += letters
        total_chars += len(stripped)

    alpha_density = alpha_chars / total_chars if total_chars else 0.0
    return _Features(
        non_blank=non_blank,
        has_structural=has_structural,
        has_tab=has_tab,
        has_separator=has_separator,
        has_dot_leader=has_dot_leader,
        has_signature=has_signature,
        max_gap=max_gap,
        gap_start_rows=tuple(gap_start_rows),
        numeric_cell_rows=tuple(numeric_cell_rows),
        alpha_density=alpha_density,
        any_lowercase=any_lowercase,
    )


def _decide(
    features: _Features, line_count: int, has_masked: bool = False
) -> SpanDecision:
    def decision(
        action: str,
        confidence: float,
        evidence: tuple[str, ...],
        trace: str,
    ) -> SpanDecision:
        return SpanDecision(action, 0, line_count, confidence, evidence, trace)

    if features.non_blank <= 1:
        return SpanDecision(
            ACTION_PRESERVE, 0, line_count, 1.0, ("single_line_block",), "fast_noop"
        )
    if has_masked:
        return SpanDecision(
            ACTION_PRESERVE,
            0,
            line_count,
            1.0,
            ("protected_tagged_table",),
            "hard_preserve",
        )
    if features.has_structural:
        return SpanDecision(
            ACTION_PRESERVE, 0, line_count, 1.0, ("structural_marker",), "hard_preserve"
        )
    if features.has_tab:
        return SpanDecision(
            ACTION_PRESERVE, 0, line_count, 0.95, ("internal_tab",), "hard_preserve"
        )
    if features.has_dot_leader:
        return SpanDecision(
            ACTION_PRESERVE,
            0,
            line_count,
            0.95,
            ("dot_leader_layout",),
            "hard_preserve",
        )
    if features.has_signature:
        return SpanDecision(
            ACTION_PRESERVE, 0, line_count, 0.9, ("signature_shape",), "hard_preserve"
        )

    if features.has_separator or features.max_gap >= 3 or features.numeric_cell_rows:
        shared_numeric = _shared_columns(
            features.numeric_cell_rows, min_rows=3, tolerance=1
        )
        shared_gaps = _shared_columns(features.gap_start_rows, min_rows=3, tolerance=1)
        if shared_numeric >= 1 and len(features.numeric_cell_rows) >= 2:
            return SpanDecision(
                ACTION_TAG_AND_PRESERVE,
                0,
                line_count,
                0.8,
                (
                    f"repeated_numeric_columns:{shared_numeric}",
                    f"numeric_rows:{len(features.numeric_cell_rows)}",
                ),
                "high_confidence_table",
            )
        if features.has_separator and shared_gaps >= 1:
            return SpanDecision(
                ACTION_TAG_AND_PRESERVE,
                0,
                line_count,
                0.75,
                ("separator_grid", f"repeated_gap_columns:{shared_gaps}"),
                "high_confidence_table",
            )
        return SpanDecision(
            ACTION_PRESERVE,
            0,
            line_count,
            0.6,
            ("layout_gap_without_alignment",),
            "candidate_preserve",
        )

    if features.alpha_density >= _MIN_PROSE_ALPHA_DENSITY and features.any_lowercase:
        return SpanDecision(
            ACTION_UNWRAP, 0, line_count, 0.7, ("ordinary_prose",), "fast_prose"
        )
    return SpanDecision(
        ACTION_PRESERVE, 0, line_count, 0.5, ("default_preserve",), "candidate_preserve"
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
    """Merge adjacent TAG_AND_PRESERVE blocks across a bounded blank line.

    Tables routinely span blank lines between caption, header, and totals.
    Two blocks that each independently qualified for a table tag and are
    separated by at most ``max_blank_lines`` blank lines are one connected
    region. Decisions already carry absolute line ranges, so adjacency is
    checked directly.
    """
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


def reflow_ascii(
    text: str,
    *,
    body_start_line: int | None = None,
    page_analysis: object | None = None,
) -> ReflowResult:
    """Run the conservative gate cascade over plain-text filing content.

    ``body_start_line`` is the first body content line (zero-based) in the
    coordinate frame of ``text``; everything before it is preserved exactly.
    With no validated body anchor the text is returned unchanged — leaving
    prose hard-wrapped is preferable to reflowing a cover, TOC, or table.
    """
    if not text or "\n" not in text or body_start_line is None:
        return ReflowResult(text)

    # Page analysis belongs to the pre-cleanup source frame. Only carry its
    # existence as decision evidence here; never reuse its offsets after
    # marker removal or any other transformation.
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
        has_masked = any("\x00" in line for line in block_lines)
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
    # Materialize merged decisions back onto block groups: a merged decision
    # spans its constituent blocks plus the bridging blank lines exactly.
    rendered: list[str] = []
    cursor = 0
    decision_index = 0
    while decision_index < len(decisions):
        decision = decisions[decision_index]
        if decision.start_line > cursor:
            rendered.append("\n".join(lines[cursor : decision.start_line]))
        group = [
            (start, end, block_lines)
            for start, end, block_lines in blocks
            if decision.start_line <= start and end <= decision.end_line
        ]
        if decision.action == ACTION_TAG_AND_PRESERVE and len(group) > 1:
            merged_lines: list[str] = []
            for position, (start, end, block_lines) in enumerate(group):
                if position:
                    merged_lines.extend(lines[group[position - 1][1] : start])
                merged_lines.extend(block_lines)
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
