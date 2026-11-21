"""Confidence evaluation, layout diagnostics, and safety vetoes.
Confidence is not an operator quality score; it states whether the resolved grid still describes
the source, and a low one carries the specific reason.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .model import (
        ResolvedGrid,
        SourceTable,
        SpanGroup,
    )


def evaluate_table_confidence(
    source_table: SourceTable,
    resolved_grid: ResolvedGrid,
    span_groups: list[SpanGroup],
) -> tuple[float, list[str]]:
    """Evaluate confidence and identify veto conditions for the resolved grid.
    Returns a confidence in ``[0, 1]`` plus the specific veto reasons when it is low.
    """
    veto_reasons: list[str] = []
    base_confidence = 1.0

    if not resolved_grid.rows or not resolved_grid.column_widths:
        veto_reasons.append("Empty table or zero resolved columns")
        return 0.0, veto_reasons

    num_rows = len(resolved_grid.rows)
    num_cols = len(resolved_grid.column_widths)

    if num_cols < 2 and len(source_table.rows) >= 3:
        raw_cell_counts = [len(r) for r in source_table.rows]
        if max(raw_cell_counts, default=0) >= 3:
            veto_reasons.append("Multi-cell source table collapsed into single column")
            base_confidence -= 0.40

    clipped_diagnostics = [d for d in resolved_grid.diagnostics if d.clipped]
    if clipped_diagnostics:
        base_confidence -= min(0.30, len(clipped_diagnostics) * 0.05)
        veto_reasons.append(f"{len(clipped_diagnostics)} cells clipped by width budget")

    if len(span_groups) > (num_rows * num_cols * 0.7):
        base_confidence -= 0.20
        veto_reasons.append("Excessive span complexity across table grid")

    final_confidence = max(0.0, min(1.0, base_confidence))
    return final_confidence, veto_reasons


__all__ = [
    "evaluate_table_confidence",
]
