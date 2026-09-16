"""Decision cascade and classification rules for layout blocks."""

from __future__ import annotations

from .features import _Features, _shared_columns
from .types import (
    _MIN_PROSE_ALPHA_DENSITY,
    ACTION_PRESERVE,
    ACTION_TAG_AND_PRESERVE,
    ACTION_UNWRAP,
    SpanDecision,
)


def _decide(
    features: _Features, line_count: int, has_masked: bool = False
) -> SpanDecision:
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


__all__ = ["_decide"]
