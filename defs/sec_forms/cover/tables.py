"""Form-aware cover page table cleaning and pseudo-table unwrapping.

Generic layout tables are unwrapped upstream by :mod:`defs.tables.false_tables`.
This module provides form-governed cover table cleaners that execute strictly
within the verified :class:`~defs.sec_forms.cover.models.CoverBoundary` to
unwrap cover-only pseudo-tables (such as annual/quarterly/transition report
period checkbox blocks) without leaking into non-cover filings or body tables.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import TYPE_CHECKING

from defs.regex import build_alternation
from defs.tables.patterns import RE_TABLE_BLOCK

if TYPE_CHECKING:
    from defs.sec_forms.cover.models import CoverBoundary
    from defs.tables.ascii_html import TableGeometry

_REPORT_TYPE_ALT = build_alternation(["annual", "transition", "quarterly"])
_REPORT_STATUTE_ALT = build_alternation(
    ["section 13", "section 15", "securities exchange act", "1934"]
)
_RE_REPORT_PERIOD_TABLE = re.compile(
    rf"(?i)\b(?:{_REPORT_TYPE_ALT})\s+report\b.*?\b(?:{_REPORT_STATUTE_ALT})\b",
    re.DOTALL,
)


def _is_report_period_table(table_block: str) -> bool:
    """Return True if the table_block text represents a statutory report period checkbox block.

    Classification is always performed against the raw ``table_block`` string from
    the document text — never against geometry rows from a prior render pass.
    Geometry may have been left behind by an upstream unwrapping step (such as
    :func:`~defs.sec_forms.cover.checkmark_rewrite.apply_cover_checkmark_decisions`)
    and can belong to a completely different table, causing misclassification of
    address or entity tables that happen to follow a report-period checkbox table.
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
    """Unwrap recognized pseudo-tables strictly within the cover boundary.

    Only tables whose start tag occurs before ``boundary.end_line`` are
    evaluated. Tables outside the cover (e.g. exhibit indices, financial
    statements) are never inspected or unwrapped.

    Geometry is looked up by the stable
    :attr:`~defs.tables.ascii_html.TableGeometry.table_index` attribute, not by
    positional index in ``table_geometries``.  This is safe even when upstream
    passes (e.g.
    :func:`~defs.sec_forms.cover.checkmark_rewrite.apply_cover_checkmark_decisions`)
    have already removed some ``<TABLE>`` blocks and evicted their geometries,
    because the remaining geometries still carry their original stable IDs.
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

    # Build a stable-ID → geometry dict so we can look up by table_index
    # rather than by sequential position in the geometries tuple.  The
    # sequential position is unreliable after any upstream pass has evicted
    # unwrapped tables from the tuple.
    geom_by_id: dict[int, TableGeometry] = {}
    for geom in table_geometries:
        tid = getattr(geom, "table_index", None)
        if tid is not None:
            geom_by_id[tid] = geom

    # Build a parallel list of (match, geometry) pairs where geometry is
    # matched by iterating through geometries whose table_index has not yet
    # been claimed.  Tables in text still appear in document order and
    # geometries in table_geometries are also in document order (by
    # table_index), so a sequential scan through surviving geometries
    # correctly pairs each remaining <TABLE> block with its geometry.
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
            # Classification is ALWAYS against the actual table_block text.
            # Geometry is only used as a rendering hint for _unwrap_table,
            # never for the classification decision itself.
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
