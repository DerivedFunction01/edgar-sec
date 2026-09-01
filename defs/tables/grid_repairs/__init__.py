"""Condition-aware column repairs and layout templates for HTML table grids."""

from __future__ import annotations

import sys

from ..patterns import YEAR_IN_HEADER_RE, YEAR_TOKEN_RE
from .base import GridRepair, GridTemplate, SpanGroup, TemplateApplier, TemplateMatcher
from .repairs import (
    attach_inline_footnotes,
    drop_empty_body_columns,
    drop_footnote_columns,
    drop_header_only_spacers,
    drop_header_only_year_spacers,
    drop_prefix_columns,
    drop_suffix_columns,
    fold_dropped_headers,
    is_section,
    merge_inline_suffix_cells,
    merge_prefix_columns,
    shift_sparse_numeric_cells_left,
)
from .templates import (
    GRID_TEMPLATES,
    HEADERLESS_MATURITY_TEMPLATE,
    REPEATED_VALUE_GROUP_TEMPLATE,
    YEAR_VALUE_GROUP_TEMPLATE,
    collapse_headerless_maturity_groups,
    collapse_span_groups,
    match_headerless_maturity_groups,
    match_repeated_value_groups,
    match_year_value_groups,
)


def apply_grid_repairs(
    rows: list[list[str]],
    header_count: int,
    *,
    debug: bool,
    span_groups: list[SpanGroup] | None = None,
) -> list[int]:
    """Apply registered grid repair passes and return the indices of retained columns."""
    repairs: list[tuple[str, GridRepair]] = [
        ("merge_prefix_columns", merge_prefix_columns),
        ("shift_sparse_numeric_cells_left", shift_sparse_numeric_cells_left),
        ("drop_header_only_spacers", drop_header_only_spacers),
        ("drop_header_only_year_spacers", drop_header_only_year_spacers),
        ("merge_inline_suffix_cells", merge_inline_suffix_cells),
        ("drop_footnote_columns", drop_footnote_columns),
        ("drop_suffix_columns", drop_suffix_columns),
        ("drop_prefix_columns", drop_prefix_columns),
    ]
    period_headers = [
        group
        for group in (span_groups or [])
        if group[0] < header_count
        and (YEAR_TOKEN_RE.match(group[3]) or YEAR_IN_HEADER_RE.search(group[3]))
    ]
    if len(period_headers) >= 2:
        repairs.extend(
            [
                ("attach_inline_footnotes", attach_inline_footnotes),
                ("drop_empty_body_columns", drop_empty_body_columns),
            ]
        )
    drop: set[int] = set()
    if span_groups:
        for template in GRID_TEMPLATES:
            matches = template.match(rows, header_count, span_groups)
            if matches:
                template.apply(rows, header_count, drop, matches)
                if debug:
                    print(
                        f"[table-debug] matched template {template.name}: "
                        f"groups={len(matches)} dropped={sorted(drop)}",
                        file=sys.stderr,
                    )
    for name, repair in repairs:
        before = len(drop)
        repair(rows, header_count, drop)
        if debug and len(drop) != before:
            print(
                f"[table-debug] applied {name}: dropped {sorted(drop)}", file=sys.stderr
            )
    kept = [
        column
        for column in range(max(map(len, rows), default=0))
        if column not in drop and any(row[column].strip() for row in rows)
    ]
    fold_dropped_headers(rows, header_count, drop, kept)
    return kept


__all__ = [
    "GRID_TEMPLATES",
    "HEADERLESS_MATURITY_TEMPLATE",
    "REPEATED_VALUE_GROUP_TEMPLATE",
    "YEAR_VALUE_GROUP_TEMPLATE",
    "GridRepair",
    "GridTemplate",
    "SpanGroup",
    "TemplateApplier",
    "TemplateMatcher",
    "apply_grid_repairs",
    "attach_inline_footnotes",
    "collapse_headerless_maturity_groups",
    "collapse_span_groups",
    "drop_empty_body_columns",
    "drop_footnote_columns",
    "drop_header_only_year_spacers",
    "drop_prefix_columns",
    "drop_suffix_columns",
    "fold_dropped_headers",
    "is_section",
    "match_headerless_maturity_groups",
    "match_repeated_value_groups",
    "match_year_value_groups",
    "merge_inline_suffix_cells",
]
