"""2D Table grid inspection and ASCII template rendering preview."""

from __future__ import annotations

import json
from typing import Any

from defs.tables.builder import HTMLTableConverter
from defs.tables.templates.dispatcher import apply_table_templates


def inspect_table_record(
    record: dict[str, Any],
    *,
    test_templates: bool = True,
) -> str:
    """Format and return detailed diagnostic view of a table record."""
    lines: list[str] = []
    lines.append(
        f"=== Table Diagnostic: {record.get('doc_id')} (Table #{record.get('table_index')}) ==="
    )
    lines.append(f"Document Path:    {record.get('document_path')}")
    lines.append(f"Form Type:        {record.get('form_type')}")
    lines.append(f"Section Item:     {record.get('item_label') or '(none)'}")
    lines.append(f"Section Heading:  {record.get('heading') or '(none)'}")
    lines.append(
        f"Raw Dimensions:   {record.get('raw_rows')} rows x {record.get('raw_cols')} cols"
    )
    lines.append(
        f"Healed Dims:      {record.get('healed_rows')} rows x {record.get('healed_cols')} cols (header_count={record.get('header_count')})"
    )
    lines.append(f"Numeric Density:  {float(record.get('numeric_density', 0.0)):.2%}")
    lines.append(f"Jitter Detected:  {record.get('has_column_jitter')}")
    lines.append(f"Split Affixes:    {record.get('has_split_affixes')}")
    lines.append("")

    grid_raw = record.get("healed_grid_json")
    if grid_raw:
        grid = json.loads(str(grid_raw))
        lines.append("--- Clean Healed 2D Grid Cells ---")
        for r_idx, row in enumerate(grid):
            lines.append(f"Row {r_idx:02d}: {row!r}")
        lines.append("")

        if test_templates:
            res = apply_table_templates(table=object(), source_grid=grid)
            if res:
                lines.append("--- Matched Template Output ---")
                lines.append(res.text.strip())
            else:
                lines.append("--- Standard HTMLTableConverter Output ---")
                conv_out = (
                    HTMLTableConverter(
                        grid=grid, header_row_count=int(record.get("header_count", 1))
                    )
                    .to_generic_table()
                    .build()
                )
                lines.append(conv_out.strip())

    return "\n".join(lines)
