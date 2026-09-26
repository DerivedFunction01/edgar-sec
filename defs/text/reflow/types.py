"""Immutable data models and action constants for ASCII reflow."""

from __future__ import annotations

import bisect
from collections.abc import Callable
from dataclasses import dataclass

from defs.tables.protection import TableSpan
from defs.text.syntax.signatures import SignatureRegion

ACTION_UNWRAP = "unwrap"
ACTION_PRESERVE = "preserve"
ACTION_TAG_AND_PRESERVE = "tag_and_preserve"

_MIN_PROSE_ALPHA_DENSITY = 0.55


@dataclass(frozen=True, slots=True)
class ReflowPolicy:
    """Controls whether prose before the body boundary may be unwrapped."""

    unwrap_pre_body_prose: bool = False
    split_structural_boundaries: bool = True
    split_bullet_items: bool = True
    relax_prose_layout_gaps: bool = False
    unwrap_bullet_continuations: bool = False
    is_checkbox_answer_line: Callable[[str], bool] | None = None
    is_page_boundary_line: Callable[[str], bool] | None = None
    is_structural_line: Callable[[str], bool] | None = None
    is_table_bridge_line: Callable[[str], bool] | None = None
    is_table_tail_line: Callable[[str], bool] | None = None
    tag_untagged_tables: bool = True
    split_table_intro: (
        Callable[[tuple[str, ...]], tuple[tuple[str, ...], tuple[str, ...]]] | None
    ) = None


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
    protected_signatures: tuple[SignatureRegion, ...] = ()


def build_line_mapper(
    decisions: tuple[SpanDecision, ...],
) -> Callable[[int], int]:
    """Map pre-reflow line numbers to post-reflow line numbers.

    ``SpanDecision`` records half-open ``[start_line, end_line)`` ranges.
    For ``ACTION_UNWRAP`` decisions, lines in ``(start_line, end_line)``
    are absorbed into ``start_line``; all subsequent lines shift down
    by ``end_line - start_line - 1``.  Other actions preserve line counts.

    The returned function runs in ``O(log k)`` where ``k`` is the number
    of unwrap decisions.
    """
    breakpoints: list[int] = []
    cumulative: list[int] = []
    running = 0
    for d in decisions:
        if d.action == ACTION_UNWRAP:
            removed = d.end_line - d.start_line - 1
            if removed > 0:
                running += removed
                breakpoints.append(d.end_line)
                cumulative.append(running)

    if not breakpoints:
        return lambda line: line

    def map_line(line: int) -> int:
        idx = bisect.bisect_right(breakpoints, line) - 1
        if idx < 0:
            return line
        return line - cumulative[idx]

    return map_line


__all__ = [
    "ACTION_PRESERVE",
    "ACTION_TAG_AND_PRESERVE",
    "ACTION_UNWRAP",
    "_MIN_PROSE_ALPHA_DENSITY",
    "ReflowPolicy",
    "ReflowResult",
    "SpanDecision",
    "build_line_mapper",
]
