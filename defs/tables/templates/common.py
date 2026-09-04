"""Common data structures and grid extraction helpers for table templates."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from defs.tables.grid_repairs import SpanGroup
from defs.tables.patterns import CURRENCY_TOKEN_RE, PAREN_SPACES_RE


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


def row_aware_fallback(source_grid: list[list[str]]) -> str | None:
    """Join recoverable cells horizontally, one logical source row per line."""
    if len(source_grid) < 2:
        return None
    rows = [[cell.strip() for cell in row if cell.strip()] for row in source_grid]
    if not rows or any(len(row) < 2 for row in rows):
        return None
    if any(not row for row in rows):
        return None
    return "\n" + "\n".join("  ".join(row) for row in rows) + "\n"


# Readability band for fallback line length: below the lower bound the output
# is fragmented soup; above the upper bound wrapping becomes unavoidable.
_ORIENT_MIN_LINE = 20
_ORIENT_MAX_LINE = 100
_ORIENT_LONG_PENALTY = 3.0
_ORIENT_STDEV_WEIGHT = 1.0


def _orientation_lines(source_grid: list[list[str]], *, row_wise: bool) -> list[str]:
    """Build candidate lines for one orientation, stripping blank spacing."""
    if row_wise:
        lines = [
            "  ".join(cell.strip() for cell in row if cell.strip())
            for row in source_grid
        ]
    else:
        column_count = max((len(row) for row in source_grid), default=0)
        lines = [
            "  ".join(
                row[column].strip()
                for row in source_grid
                if column < len(row) and row[column].strip()
            )
            for column in range(column_count)
        ]
    return [line for line in lines if line.strip()]


def _orientation_score(lines: list[str]) -> float:
    """Score candidate lines; lower is better (readability, not wrapping)."""
    if not lines:
        return float("inf")
    lengths = [len(line) for line in lines]
    mean = sum(lengths) / len(lengths)
    if mean == 0:
        return float("inf")
    variance = sum((length - mean) ** 2 for length in lengths) / len(lengths)
    stdev = variance**0.5
    # Distance outside the readable band dominates; wrap-heavy and soup-like
    # shapes both score poorly.
    band_penalty = 0.0
    if mean < _ORIENT_MIN_LINE:
        band_penalty = (_ORIENT_MIN_LINE - mean) * _ORIENT_LONG_PENALTY
    elif mean > _ORIENT_MAX_LINE:
        band_penalty = (mean - _ORIENT_MAX_LINE) * _ORIENT_LONG_PENALTY
    return band_penalty + _ORIENT_STDEV_WEIGHT * (stdev / mean)


def oriented_prose_fallback(source_grid: list[list[str]]) -> str | None:
    """Choose row-wise or column-wise prose orientation by line statistics.

    Compares the mean line length and its spread for both orientations and
    picks the readable one. Column-oriented tables (each column a distinct
    topic) render one block per column; label/value and list shapes stay
    row-wise. Ties resolve to row-wise to preserve source order. Returns
    ``None`` when neither orientation is meaningful (caller keeps its own
    fallback).
    """
    if len(source_grid) < 2:
        return None
    populated_counts = [sum(1 for cell in row if cell.strip()) for row in source_grid]
    # Orientation scoring compares line shapes; mixed-width grids (a full-width
    # title row plus data rows) have no meaningful orientation and stay on the
    # vertical unwrap path.
    if len({count for count in populated_counts if count}) != 1:
        return None
    if not any(count >= 2 for count in populated_counts):
        return None
    populated = any(any(cell.strip() for cell in row) for row in source_grid)
    if not populated:
        return None
    row_lines = _orientation_lines(source_grid, row_wise=True)
    column_lines = _orientation_lines(source_grid, row_wise=False)
    if not row_lines or not column_lines:
        return None
    row_score = _orientation_score(row_lines)
    column_score = _orientation_score(column_lines)
    chosen = row_lines if row_score <= column_score else column_lines
    return "\n" + "\n".join(chosen) + "\n"


def cell_text(cell: object, *, join_fragmented_anchors: bool = False) -> str:
    """Extract, clean, and normalize text inside a single table cell."""
    anchors = cell.find_all("a")
    fragmented = (
        join_fragmented_anchors
        and len(anchors) >= 3
        and any(
            len(anchor.get_text(strip=True)) == 1
            and anchor.get_text(strip=True).islower()
            for anchor in anchors
        )
    )
    text = cell.get_text(separator=" ", strip=True)
    if fragmented:
        for index, anchor in enumerate(anchors[:-1]):
            fragment = anchor.get_text(strip=True)
            following = anchors[index + 1].get_text(strip=True)
            if len(fragment) == 1 and fragment.islower() and following[:1].islower():
                text = re.sub(
                    rf"(?<!\w){re.escape(fragment)}\s+(?={re.escape(following[:1])})",
                    fragment,
                    text,
                    count=1,
                )
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s+([.,;:!?])", r"\1", text)
    text = re.sub(r"(?<=\d)\s+%", "%", text)
    text = re.sub(r"\b([A-Z]) (?=[a-z])", r"\1", text)
    text = re.sub(r"\.{2,}", " ", text)
    text = re.sub(rf"({CURRENCY_TOKEN_RE.pattern})\s+(?=\(?\s*[\d])", r"\1", text)
    text = PAREN_SPACES_RE.sub(r"(\1)", text)
    return re.sub(r"\(\s+(?=[\d])", "(", text)


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
    table: object, *, with_spans: bool = False, join_fragmented_anchors: bool = False
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
            occupied[(r, c)] = cell_text(
                cell, join_fragmented_anchors=join_fragmented_anchors
            )
            if colspan > 1:
                span_groups.append(
                    (
                        r,
                        c,
                        c + colspan,
                        cell_text(
                            cell, join_fragmented_anchors=join_fragmented_anchors
                        ),
                    )
                )
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
