"""ASCII logical-unit classification and non-mutating healed analysis view.

Splits a line stream into paragraph, list, table, and heading units using
double-newline boundaries and alignment heuristics. Paragraphs are healed
(single-newline soft wraps joined) for analysis while the original source
line span is preserved for offset mapping.

This module is form-neutral: it classifies structure only. Body/prose
scoring against form-specific vocabulary lives in ``defs.text.bow`` and the
form evidence packs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from defs.text.tokens import RE_BULLET_PREFIX


@dataclass(frozen=True, slots=True)
class LogicalUnit:
    """A single logical unit in the source document.

    ``text`` is the healed analysis view (soft wraps joined for paragraphs,
    original alignment preserved for tables). ``start_line``/``end_line``
    map back to the original source lines.
    """

    kind: str
    start_line: int
    end_line: int
    text: str

    @property
    def line_count(self) -> int:
        return self.end_line - self.start_line + 1


def _line_offsets(lines: list[str]) -> list[int]:
    """Return the character offset of the start of each line in the source."""
    offsets = [0]
    for line in lines:
        offsets.append(offsets[-1] + len(line) + 1)
    return offsets


def _is_table_row(line: str) -> bool:
    """Return whether a line looks like a fixed-width table row.

    Table rows have multi-space whitespace gutters (column separators) or
    are full-width separator lines.
    """
    stripped = line.strip()
    if not stripped:
        return False
    if re.match(r"^[-=_+]+$", stripped.replace(" ", "")):
        return True
    return bool(re.search(r"\S {2,}\S", line))


def _positions_overlap(
    reference: set[int], candidate: set[int], tolerance: int = 2
) -> bool:
    """Return whether any candidate position falls within ``tolerance`` of a reference position."""
    for ref in reference:
        for cand in candidate:
            if abs(ref - cand) <= tolerance:
                return True
    return False


def _rows_are_aligned(lines: list[str]) -> bool:
    """Return whether adjacent table-like lines share column gutter positions."""
    gutter_positions: list[set[int]] = []
    for line in lines:
        positions = {m.start() for m in re.finditer(r"(?<=\S) {2,}(?=\S)", line)}
        if positions:
            gutter_positions.append(positions)
    if len(gutter_positions) < 2:
        return False
    reference = gutter_positions[0]
    matches = sum(
        1 for pos in gutter_positions[1:] if _positions_overlap(reference, pos)
    )
    return matches >= len(gutter_positions) // 2


def _is_list_item(line: str) -> bool:
    """Return whether a line starts a bulleted or numbered list item."""
    stripped = line.strip()
    if not stripped:
        return False
    first_token = stripped.split(maxsplit=1)[0]
    if RE_BULLET_PREFIX.match(first_token):
        return True
    return bool(re.match(r"^\s*[\(\[]?[a-zA-Z0-9]+[\.\)\]]", stripped))


def _heal_paragraph(lines: list[str]) -> str:
    """Join single-newline soft wraps within a paragraph block."""
    joined: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if joined and not re.search(r"[-,;:]$", joined[-1]):
            joined[-1] = f"{joined[-1]} {stripped}"
        else:
            joined.append(stripped)
    return " ".join(joined)


def _classify_block(lines: list[str]) -> str:
    """Classify a double-newline-delimited block of lines."""
    non_empty = [line for line in lines if line.strip()]
    if not non_empty:
        return "blank"
    if (
        all(_is_table_row(line) for line in non_empty)
        and len(non_empty) >= 2
        and _rows_are_aligned(non_empty)
    ):
        return "table"
    if any(_is_table_row(line) for line in non_empty) and len(non_empty) >= 2:
        table_lines = sum(1 for line in non_empty if _is_table_row(line))
        if table_lines >= len(non_empty) // 2 and _rows_are_aligned(non_empty):
            return "table"
    if all(_is_list_item(line) for line in non_empty) and len(non_empty) >= 2:
        return "list"
    if len(non_empty) == 1 and _is_list_item(non_empty[0]):
        return "list"
    return "paragraph"


def classify_units(text: str) -> list[LogicalUnit]:
    """Split source text into logical units.

    Double-newline runs separate blocks. Each block is classified as a
    paragraph, list, table, or blank. Paragraph text is healed (soft wraps
    joined); tables and lists retain original line structure.
    """
    if not text:
        return []
    lines = text.splitlines()
    if not lines:
        return []

    blocks: list[list[tuple[int, str]]] = []
    current: list[tuple[int, str]] = []
    for index, line in enumerate(lines):
        if not line.strip():
            if current:
                blocks.append(current)
                current = []
            continue
        current.append((index, line))
    if current:
        blocks.append(current)

    units: list[LogicalUnit] = []
    for block in blocks:
        start_line = block[0][0]
        end_line = block[-1][0]
        raw_lines = [line for _, line in block]
        kind = _classify_block(raw_lines)

        if kind == "blank":
            continue
        if kind == "paragraph":
            healed = _heal_paragraph(raw_lines)
            units.append(
                LogicalUnit(
                    kind=kind, start_line=start_line, end_line=end_line, text=healed
                )
            )
        else:
            units.append(
                LogicalUnit(
                    kind=kind,
                    start_line=start_line,
                    end_line=end_line,
                    text="\n".join(raw_lines),
                )
            )

    return units


def units_after(units: list[LogicalUnit], line: int) -> list[LogicalUnit]:
    """Return units whose start_line is at or after ``line``."""
    return [unit for unit in units if unit.start_line >= line]


def line_offset(lines: list[str], line: int) -> int:
    """Return the character offset of the start of ``line``."""
    return _line_offsets(lines)[line]


__all__ = [
    "LogicalUnit",
    "classify_units",
    "line_offset",
    "units_after",
]
