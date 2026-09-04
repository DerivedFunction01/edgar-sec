"""Scoped 2D template repair for ASC 820 fair value measurement hierarchy matrices."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from defs.tables.builder import HTMLTableConverter
from defs.tables.currencies import detect_currency_affix, format_currency
from defs.tables.tokens import ALL_CURRENCY_SYMBOLS

if TYPE_CHECKING:
    from defs.sec_forms.context import SectionContext

_LEVEL_1_RE = re.compile(r"\blevel\s*1\b", re.IGNORECASE)
_LEVEL_2_RE = re.compile(r"\blevel\s*2\b", re.IGNORECASE)
_LEVEL_3_RE = re.compile(r"\blevel\s*3\b", re.IGNORECASE)


def _is_fair_value_matrix(grid: list[list[str]]) -> bool:
    """Check if table headers contain Level 1/2/3 hierarchy columns."""
    header_text = " ".join(c.lower() for r in grid[:3] for c in r if c.strip())
    return bool(
        _LEVEL_1_RE.search(header_text)
        and _LEVEL_2_RE.search(header_text)
        and _LEVEL_3_RE.search(header_text)
    )


def fair_value_template(
    source_grid: list[list[str]],
    *,
    section_context: SectionContext | None = None,
) -> str | None:
    """Repair and project jittered fair value 3-level matrices into clean 2D tabular layout."""
    _ = section_context
    if len(source_grid) < 4 or len(source_grid) > 80:
        return None

    if not _is_fair_value_matrix(source_grid):
        return None

    # Check for column jitter across substantive numeric rows
    patterns: set[tuple[int, ...]] = set()
    for row in source_grid[2:]:
        if not row or not row[0].strip():
            continue
        first = row[0].strip()
        if first.lower().startswith("total") or first.endswith(":"):
            continue
        data_cells = row[1:]
        indices = tuple(i for i, c in enumerate(data_cells, start=1) if c.strip())
        # Only count rows that actually have data cells
        if len(indices) >= 2:
            patterns.add(indices)

    if len(patterns) <= 1:
        return None

    currency_symbol, is_suffix = detect_currency_affix(source_grid)
    headers = ["Asset / Liability Class", "Level 1", "Level 2", "Level 3", "Total"]

    repaired_rows: list[list[str]] = []
    for row in source_grid[2:]:
        non_empty = [c.strip() for c in row if c.strip()]
        if not non_empty:
            continue

        label = non_empty[0]
        numeric_vals = [c for c in non_empty[1:] if c not in ALL_CURRENCY_SYMBOLS]

        if len(numeric_vals) >= 4:
            vals = [
                format_currency(v, currency_symbol, is_suffix=is_suffix)
                if re.match(r"^\d", v)
                else v
                for v in numeric_vals[:4]
            ]
            repaired_rows.append([label] + vals)
        elif numeric_vals:
            padded = [label] + numeric_vals[:4] + [""] * max(0, 4 - len(numeric_vals))
            repaired_rows.append(padded)
        else:
            repaired_rows.append([label, "", "", "", ""])

    if not repaired_rows:
        return None

    clean_grid = [headers] + repaired_rows
    return (
        HTMLTableConverter(grid=clean_grid, header_row_count=1)
        .to_generic_table()
        .build()
    )
