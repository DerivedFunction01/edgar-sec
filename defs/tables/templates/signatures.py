"""Signature-block component: detection, healing, and canonical rendering.

This module is the singular owner of the signature table family: detection,
marker normalization, mangled-name healing, record reconstruction, and
canonical rendering. ``presentation.py`` routes here and must not carry its
own signature layout logic. Semantic vocabulary (markers, officer titles)
lives in ``defs.taxonomy.components.signatures``; generic line primitives
live in ``defs.text.patterns`` and ``defs.text.signatures``.
"""

from __future__ import annotations

import re

from defs.tables.builder import HTMLTableConverter
from defs.text.dates import contains_date
from defs.text.signatures import (
    heal_mangled_signature_text,
    normalize_signature_marker,
    signature_block_has_mangled_text,
)

from .common import span_grid

_MARKER_START_RE = re.compile(r"^(?:/s/|\*)\s*", re.IGNORECASE)


def _same_text(a: str, b: str) -> bool:
    """Compare text ignoring all whitespace and letter case."""
    return re.sub(r"\s+", "", a).casefold() == re.sub(r"\s+", "", b).casefold()


def _dedupe_join(left: str, right: str) -> str:
    """Join continuation text without repeating an already-present value."""
    if not right:
        return left
    if not left or _same_text(left, right):
        return right
    if right.casefold() in left.casefold():
        return left
    if left.casefold() in right.casefold():
        return right
    return f"{left} {right}"


def _normalize_grid(source_grid: list[list[str]]) -> list[list[str]]:
    """Canonicalize markers, heal mangled text, and merge name continuations."""
    grid = [row[:] for row in source_grid]
    if any(
        signature_block_has_mangled_text((" ".join(c for c in row if c.strip()),))
        for row in grid
    ):
        grid = [[heal_mangled_signature_text(cell) for cell in row] for row in grid]
    else:
        grid = [[normalize_signature_marker(cell) for cell in row] for row in grid]
    for index, row in enumerate(grid[:-1]):
        marker_column = next(
            (c for c, cell in enumerate(row) if cell.strip().startswith("/s/")),
            None,
        )
        next_values = [cell.strip() for cell in grid[index + 1] if cell.strip()]
        if marker_column is None or not next_values:
            continue
        signer = next_values[0]
        marker_name = row[marker_column][3:].strip()
        if _same_text(signer, marker_name):
            # Prefer the mixed-case spelling over an all-caps variant.
            all_caps = lambda value: (
                value == value.upper() and any(c.isalpha() for c in value)
            )
            row[marker_column] = (
                f"/s/ {marker_name}" if all_caps(signer) else f"/s/ {signer}"
            )
            grid[index + 1] = [
                "" if _same_text(cell, signer) else cell for cell in grid[index + 1]
            ]
        elif len(next_values) == 1:
            row[marker_column] = f"/s/ {signer}"
            grid[index + 1] = [""] * len(grid[index + 1])
    return grid


def _signature_line(cell: str) -> str:
    """Join marker, signer, and title fragments of one cell canonically."""
    if cell.casefold().startswith("by:") and "/s/" in cell:
        return cell
    match = _MARKER_START_RE.match(cell)
    if not match:
        return cell
    return normalize_signature_marker(cell)


def signature_template(table: object) -> str | None:
    """Detect, heal, and render a signature block, or ``None`` when vetoed."""
    source_grid, _ = span_grid(table, with_spans=True)
    if not source_grid:
        return None
    normalized = _normalize_grid(source_grid)
    all_text = " ".join(cell for row in normalized for cell in row if cell)
    marker_positions = [
        (row_index, column)
        for row_index, row in enumerate(normalized)
        for column, cell in enumerate(row)
        if _MARKER_START_RE.match(cell.strip())
    ]
    if "/s/" not in all_text and len(marker_positions) < 2:
        return None

    has_asterisk_marker = any(cell.strip() == "*" for row in normalized for cell in row)
    if has_asterisk_marker and len(marker_positions) >= 2:
        rows = [row for row in table.find_all("tr") if row.get_text(" ", strip=True)]
        records: list[list[str]] = []
        for row_index, _ in marker_positions:
            if row_index + 1 >= len(normalized) or row_index + 1 >= len(rows):
                return None
            marker = next(
                cell.strip() for cell in normalized[row_index] if cell.strip()
            )
            date = next(
                (cell.strip() for cell in normalized[row_index] if contains_date(cell)),
                "",
            )
            detail = next(
                (cell.strip() for cell in normalized[row_index + 1] if cell.strip()),
                "",
            )
            next_style = " ".join(
                cell.get("style", "")
                for cell in rows[row_index + 1].find_all(["td", "th"])
            ).casefold()
            if not date or not detail or "border-top:" not in next_style:
                return None
            signature = _signature_line(f"{marker} {detail}")
            if signature.casefold().startswith("/s/"):
                signer = signature[3:].strip()
                if detail.casefold().startswith(signer.casefold()):
                    signature = f"/s/ {detail[len(signer) :].strip()}"
            records.append([signature, date])
        return (
            HTMLTableConverter(
                grid=[["Signature and Title", "Date"], *records], header_row_count=1
            )
            .to_generic_table()
            .build()
        )

    header_index = next(
        (
            index
            for index, row in enumerate(normalized)
            if (
                "title" in {cell.casefold() for cell in row if cell}
                and any(
                    cell.casefold() in {"name", "signature"} for cell in row if cell
                )
            )
        ),
        None,
    )
    if header_index is not None:
        header = normalized[header_index]
        starts = [
            index
            for index, cell in enumerate(header)
            if cell.casefold() in {"name", "signature", "title", "date"}
        ]
        starts.sort()
        header_labels = {cell.casefold() for cell in header if cell}
        has_date_column = "date" in header_labels
        groups = [
            (
                starts[index],
                starts[index + 1] if index + 1 < len(starts) else len(header),
            )
            for index in range(len(starts))
        ]
        width = len(starts)
        width = len(starts)
        records: list[list[str]] = []
        for row in normalized[header_index + 1 :]:
            values = [
                " ".join(cell for cell in row[start:end] if cell).strip()
                for start, end in groups
            ]
            if not any(values):
                continue
            has_marker = any("/s/" in value for value in values)
            if records and not has_marker and not contains_date(" ".join(values)):
                records[-1] = [
                    _dedupe_join(records[-1][index], values[index])
                    for index in range(width)
                ]
            else:
                records.append(values)
        # Preserve the source header's own label; default to "Signature".
        header_name = (
            "Name"
            if "name" in header_labels and "signature" not in header_labels
            else "Signature"
        )
        out_header = (
            [header_name, "Title", "Date"]
            if has_date_column
            else [header_name, "Title"]
        )
        return (
            HTMLTableConverter(grid=[out_header, *records], header_row_count=1)
            .to_generic_table()
            .build()
        )

    slash_positions = slash_positions_of(normalized)
    if (
        len(slash_positions) >= 2
        and len({column for _, column in slash_positions}) >= 2
    ):
        midpoint = len(normalized[0]) // 2
        rows = []
        for row in normalized:
            left = " ".join(cell for cell in row[:midpoint] if cell).strip()
            right = " ".join(cell for cell in row[midpoint:] if cell).strip()
            if left or right:
                rows.append((left, right))
        width = max((len(left) for left, _ in rows), default=0)
        lines = [f"{left.ljust(width)}  {right}".rstrip() for left, right in rows]
        return "\n" + "\n".join(lines) + "\n"

    lines = [_signature_line(cell) for row in normalized for cell in row if cell]
    if len(marker_positions) == 1 and lines:
        rendered: list[str] = []
        for line in lines:
            if rendered and rendered[-1].casefold() in {"by", "by:"} and "/s/" in line:
                rendered[-1] = f"By: {line}"
            else:
                rendered.append(line)
        return "\n" + "\n".join(rendered) + "\n"

    if "by:" not in all_text.casefold():
        return None
    midpoint = max(1, len(normalized[0]) // 2)
    rows = []
    for row in normalized:
        left = " ".join(cell for cell in row[:midpoint] if cell).strip()
        right = " ".join(cell for cell in row[midpoint:] if cell).strip()
        if left or right:
            rows.append([left, right])
    return HTMLTableConverter(grid=rows, header_row_count=0).to_generic_table().build()


def slash_positions_of(grid: list[list[str]]) -> list[tuple[int, int]]:
    """Return (row, column) positions of cells containing ``/s/``."""
    return [
        (row_index, column)
        for row_index, row in enumerate(grid)
        for column, cell in enumerate(row)
        if "/s/" in cell
    ]
