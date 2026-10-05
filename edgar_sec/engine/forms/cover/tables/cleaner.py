"""Form-aware cover page table cleaning and pseudo-table unwrapping. Cleaners run
strictly inside the verified CoverBoundary, so cover-only pseudo-tables never leak
into non-cover filings or body tables.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from edgar_sec.engine.forms.cover.models import CoverBoundary
from edgar_sec.engine.tables.ascii_html.model import TableGeometry
from edgar_sec.engine.tables.patterns import RE_TABLE_BLOCK
from edgar_sec.foundation.regex.builder import build_alternation

_REPORT_TYPE_ALT = build_alternation(["annual", "transition", "quarterly"])
_REPORT_STATUTE_ALT = build_alternation(
    ["section 13", "section 15", "securities exchange act", "1934"]
)
_RE_REPORT_PERIOD_TABLE = re.compile(
    rf"(?i)\b(?:{_REPORT_TYPE_ALT})\s+report\b.*?\b(?:{_REPORT_STATUTE_ALT})\b",
    re.DOTALL,
)


def _is_report_period_table(table_block: str) -> bool:
    """Whether the block is a statutory report period checkbox block. Classification
    always runs on the raw table text, never geometry rows from another table.
    """
    return bool(_RE_REPORT_PERIOD_TABLE.search(table_block))


def _unwrap_table(
    table_block: str,
    geometry: TableGeometry | None = None,
) -> str:
    """Unwrap a false table into line-delimited prose."""
    if geometry is not None and geometry.rows:
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
    """Unwrap pseudo-tables strictly within the cover boundary. Geometry is matched by
    stable `table_index`: position breaks once an upstream pass evicts tables.
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

    # Look up by stable table_index, not position: position is unreliable once
    # an upstream pass has evicted unwrapped tables from the tuple.
    geom_by_id: dict[int, TableGeometry] = {}
    for geom in table_geometries:
        tid = getattr(geom, "table_index", None)
        if tid is not None:
            geom_by_id[tid] = geom

    # Pair blocks with surviving geometries by sequential scan: both are in
    # document order, and unwrapped blocks lose their geometry in the same step.
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
            # Classification always against the block text; geometry is a
            # rendering hint for _unwrap_table only.
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
