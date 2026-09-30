"""Form-aware cover page table cleaning and pseudo-table unwrapping.

Generic layout tables are unwrapped upstream by false_tables.
This module provides form-governed cover table cleaners that execute strictly
within the verified CoverBoundary to unwrap cover-only pseudo-tables (such as
annual/quarterly/transition report period checkbox blocks) without leaking into
non-cover filings or body tables.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import TYPE_CHECKING

from edgar_sec.engine.tables.patterns import RE_TABLE_BLOCK
from edgar_sec.foundation.regex.builder import build_alternation

if TYPE_CHECKING:
    from edgar_sec.engine.forms.cover.models import CoverBoundary
    from edgar_sec.engine.tables.ascii_html.geometry import TableGeometry

_REPORT_TYPE_ALT = build_alternation(["annual", "transition", "quarterly"])
_REPORT_STATUTE_ALT = build_alternation(
    ["section 13", "section 15", "securities exchange act", "1934"]
)
_RE_REPORT_PERIOD_TABLE = re.compile(
    rf"(?i)\b(?:{_REPORT_TYPE_ALT})\s+report\b.*?\b(?:{_REPORT_STATUTE_ALT})\b",
    re.DOTALL,
)


def _is_report_period_table(table_block: str) -> bool:
    """Return True if table_block text represents a report period checkbox block."""
    return bool(_RE_REPORT_PERIOD_TABLE.search(table_block))


def _unwrap_table(
    table_block: str,
    geometry: TableGeometry | None = None,
) -> str:
    """Unwrap a false table into line-delimited prose."""
    if geometry is not None and getattr(geometry, "rows", None):
        rows = [[cell.strip() for cell in row if cell.strip()] for row in geometry.rows]
        rows = [row for row in rows if row]
        if rows:
            return "\n".join(" ".join(row) for row in rows)
    inner = table_block[len("<TABLE>") : -len("</TABLE>")].strip()
    lines = [line.strip() for line in inner.splitlines() if line.strip()]
    return "\n".join(lines)


def clean_cover_tables(
    text: str,
    boundary: CoverBoundary,
    table_geometries: tuple[TableGeometry, ...] = (),
    *,
    enabled_cleaners: Sequence[str] = ("report_period",),
) -> tuple[str, tuple[TableGeometry, ...]]:
    """Unwrap recognized pseudo-tables strictly within the cover boundary.

    Only tables whose start tag occurs before ``boundary.end_line`` are
    evaluated. Tables outside the cover (e.g. exhibit indices, financial
    statements) are never inspected or unwrapped.
    """
    if boundary.end_line is None or not enabled_cleaners or "<TABLE>" not in text:
        return text, table_geometries

    lines = text.splitlines(keepends=True)
    if boundary.end_line > len(lines):
        cover_char_end = len(text)
    else:
        cover_char_end = sum(len(line) for line in lines[: boundary.end_line])

    matches = list(RE_TABLE_BLOCK.finditer(text))
    if not matches:
        return text, table_geometries

    surviving_geoms = sorted(
        table_geometries, key=lambda g: getattr(g, "table_index", 0)
    )
    match_geom_pairs: list[tuple[re.Match[str], TableGeometry | None]] = []
    geom_iter = iter(surviving_geoms)
    next_geom: TableGeometry | None = next(geom_iter, None)
    for match in matches:
        match_geom_pairs.append((match, next_geom))
        next_geom = next(geom_iter, None)

    replacements: dict[int, str] = {}
    kept_geometries: list[TableGeometry] = []

    for idx, (match, geometry) in enumerate(match_geom_pairs):
        if match.start() < cover_char_end:
            table_block = match.group(0)
            should_unwrap = False
            if "report_period" in enabled_cleaners and _is_report_period_table(
                table_block
            ):
                should_unwrap = True

            if should_unwrap:
                replacements[idx] = _unwrap_table(table_block, geometry)
                continue

        if geometry is not None:
            kept_geometries.append(geometry)

    if not replacements:
        return text, table_geometries

    pieces: list[str] = []
    last_end = 0
    for idx, (match, _) in enumerate(match_geom_pairs):
        if idx in replacements:
            pieces.append(text[last_end : match.start()])
            pieces.append(replacements[idx])
            last_end = match.end()

    pieces.append(text[last_end:])
    new_text = "".join(pieces)
    return new_text, tuple(kept_geometries)


__all__ = [
    "clean_cover_tables",
]
