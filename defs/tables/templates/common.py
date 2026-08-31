"""Common data structures and grid extraction helpers for table templates."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from defs.tables.grid_repairs import SpanGroup
from defs.tables.patterns import PAREN_SPACES_RE


@dataclass(frozen=True)
class TemplateResult:
    """Return value from table template matchers.

    Attributes:
        text:         The rendered string to replace the table node with.
        bypass_guard: When True, the caller must skip the numeric-density
                      guard and unwrap check.  Use this for templates that
                      intentionally handle non-numeric prose (checkboxes,
                      cover-page layout grids, etc.) where the density test
                      would wrongly discard a successful render.
    """

    text: str
    bypass_guard: bool = field(default=False)


def cell_text(cell: object) -> str:
    """Extract, clean, and normalize text inside a single table cell."""
    text = cell.get_text(separator=" ", strip=True)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s+([.,;:!?])", r"\1", text)
    text = re.sub(r"\b([A-Z]) (?=[a-z])", r"\1", text)
    text = re.sub(r"\.{2,}", " ", text)
    text = PAREN_SPACES_RE.sub(r"(\1)", text)
    return re.sub(r"^\$\s+(\d)", r"$\1", text)


def cell_lines(cell: object) -> list[str]:
    """Extract visible block lines without losing layout-only line breaks."""
    blocks = cell.find_all("div", recursive=False)
    if blocks:
        return [cell_text(block) for block in blocks if cell_text(block)]
    text = cell_text(cell)
    return [line.strip() for line in text.splitlines() if line.strip()] or (
        [text] if text else []
    )


def span_grid(
    table: object, *, with_spans: bool = False
) -> list[list[str]] | tuple[list[list[str]], list[SpanGroup]]:
    """Build a 2D text matrix respecting HTML cell colspans and rowspans."""
    occupied: dict[tuple[int, int], str] = {}
    span_groups: list[SpanGroup] = []
    rows = table.find_all("tr")
    for r, tr in enumerate(rows):
        c = 0
        for cell in tr.find_all(["td", "th"]):
            while (r, c) in occupied:
                c += 1
            try:
                colspan = max(1, int(cell.get("colspan", 1)))
                rowspan = max(1, int(cell.get("rowspan", 1)))
            except (TypeError, ValueError):
                colspan = rowspan = 1
            occupied[(r, c)] = cell_text(cell)
            if colspan > 1:
                span_groups.append((r, c, c + colspan, cell_text(cell)))
            for rr in range(r, r + rowspan):
                for cc in range(c, c + colspan):
                    occupied.setdefault((rr, cc), "")
            c += colspan
    if not occupied:
        return ([], []) if with_spans else []
    max_r = max(r for r, _ in occupied) + 1
    max_c = max(c for _, c in occupied) + 1
    included_rows = [
        r
        for r in range(max_r)
        if any(occupied.get((r, c), "").strip() for c in range(max_c))
    ]
    grid = [[occupied.get((r, c), "") for c in range(max_c)] for r in included_rows]
    if with_spans:
        row_map = {source: target for target, source in enumerate(included_rows)}
        span_groups = [
            (row_map[row], start, end, label)
            for row, start, end, label in span_groups
            if row in row_map
        ]
        return grid, span_groups
    return grid


__all__ = [
    "TemplateResult",
    "cell_lines",
    "cell_text",
    "span_grid",
]
