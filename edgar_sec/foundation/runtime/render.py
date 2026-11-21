"""Component-based terminal renderer for pipeline command output."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from itertools import groupby
import sys


__all__ = ["Grid", "KeyValueRow", "ProseRow", "RenderComponent", "render_output"]


@dataclass(frozen=True, slots=True)
class KeyValueRow:
    """A label → value pair, rendered as an aligned row."""

    label: str
    value: str


@dataclass(frozen=True, slots=True)
class ProseRow:
    """A plain text line with no alignment."""

    text: str


@dataclass(frozen=True, slots=True)
class Grid:
    """An aligned table with headers and data rows."""

    headers: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]


RenderComponent = KeyValueRow | ProseRow | Grid


def render_output(
    components: Iterable[RenderComponent],
    title: str = "",
) -> None:
    """Print structured components as readable terminal output.

    Preserves natural component sequence, groups consecutive KeyValueRows
    for column alignment, and minimizes I/O overhead.
    """
    buffer: list[str] = []

    if title:
        buffer.append(title)

    # Group consecutive components by type in a single pass to preserve layout order
    for comp_type, group in groupby(components, type):
        items = list(group)

        if issubclass(comp_type, KeyValueRow):
            # Compute width across the contiguous block of KeyValueRows
            max_label = max(len(r.label) for r in items)
            buffer.extend(f"  {r.label.ljust(max_label)}  {r.value}" for r in items)

        elif issubclass(comp_type, ProseRow):
            buffer.extend(f"  {r.text}" for r in items)

        elif issubclass(comp_type, Grid):
            for grid in items:
                headers = grid.headers
                col_count = len(headers)
                if not col_count:
                    continue

                widths = [len(h) for h in headers]
                # Single pass across rows to compute column widths
                for row in grid.rows:
                    for i, cell in enumerate(row[:col_count]):
                        if len(cell) > widths[i]:
                            widths[i] = len(cell)

                # Format header and divider
                buffer.append(
                    "  " + "  ".join(h.ljust(widths[i]) for i, h in enumerate(headers))
                )
                buffer.append("  " + "  ".join("-" * w for w in widths))

                # Render data rows avoiding repeated index checks
                for row in grid.rows:
                    cells = [
                        (row[i] if i < len(row) else "").ljust(widths[i])
                        for i in range(col_count)
                    ]
                    buffer.append("  " + "  ".join(cells))

    if buffer:
        sys.stdout.write("\n".join(buffer) + "\n")
