"""Feature extraction for layout analysis, column alignment, and character density."""

from __future__ import annotations

from dataclasses import dataclass

from defs.tables.tokens import is_numeric_cell, is_prefix_token
from defs.text.patterns import (
    RE_COLUMN_GAP,
    RE_DOT_LEADER,
    RE_PAGE_NUMBER_SUFFIX,
    RE_SEPARATOR_RUN,
    RE_STRUCTURAL_SGML,
)
from defs.text.signatures import is_signature_label_line


@dataclass(frozen=True, slots=True)
class _Features:
    non_blank: int
    has_structural: bool
    has_tab: bool
    has_separator: bool
    has_dot_leader: bool
    has_signature: bool
    max_gap: int
    gap_start_rows: tuple[tuple[int, ...], ...]
    numeric_cell_rows: int
    shared_numeric_columns: int
    alpha_density: float
    any_lowercase: bool


def _line_gap_starts(line: str) -> tuple[int, ...]:
    """Positions of internal whitespace runs that separate layout columns.

    Leading indentation is not a gap: indented prose and list items are
    eligible for unwrapping, so gap detection starts after the first
    content character.
    """
    stripped_end = len(line.rstrip())
    content_start = len(line) - len(line.lstrip())
    starts: list[int] = []
    for match in RE_COLUMN_GAP.finditer(line[:stripped_end]):
        if match.start() < content_start:
            continue
        if len(match.group()) >= 3:
            starts.append(match.start())
    return tuple(starts)


def _numeric_cell_starts(line: str) -> tuple[int, ...]:
    """Positions where a numeric/currency cell begins right after a gap."""
    stripped_end = len(line.rstrip())
    content_start = len(line) - len(line.lstrip())
    starts: list[int] = []
    for match in RE_COLUMN_GAP.finditer(line[:stripped_end]):
        if match.start() < content_start:
            continue
        tail = line[match.end() :].strip().split()
        if not tail:
            continue
        if is_numeric_cell(tail[0]):
            starts.append(match.end())
        elif len(tail) > 1 and is_prefix_token(tail[0]):
            candidate = f"{tail[0]}{tail[1]}"
            if is_numeric_cell(candidate) or is_numeric_cell(f"{tail[0]} {tail[1]}"):
                starts.append(match.end())
            elif len(tail) > 2 and is_prefix_token(tail[1]):
                candidate3 = f"{tail[0]}{tail[1]}{tail[2]}"
                if is_numeric_cell(candidate3) or is_numeric_cell(
                    f"{tail[0]} {tail[1]} {tail[2]}"
                ):
                    starts.append(match.end())
    return tuple(starts)


def _shared_columns(
    cell_rows: tuple[tuple[int, ...], ...],
    *,
    min_rows: int,
    tolerance: int = 1,
) -> int:
    """Count columns covered by at least ``min_rows`` rows within tolerance."""
    if len(cell_rows) < min_rows:
        return 0
    counted: list[int] = []
    shared = 0
    for anchor in sorted({p for row in cell_rows for p in row}):
        lo, hi = anchor - tolerance, anchor + tolerance
        covering = sum(1 for row in cell_rows if any(lo <= p <= hi for p in row))
        if covering >= min_rows and not any(
            counted_col - tolerance <= anchor <= counted_col + tolerance
            for counted_col in counted
        ):
            shared += 1
            counted.append(anchor)
    return shared


def _compute_features(lines: tuple[str, ...]) -> _Features:
    non_blank = 0
    has_structural = has_tab = has_separator = False
    has_dot_leader = has_signature = False
    max_gap = 0
    gap_start_rows: list[tuple[int, ...]] = []
    numeric_cell_rows: list[tuple[int, ...]] = []
    alpha_chars = 0
    total_chars = 0
    any_lowercase = False

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        non_blank += 1
        if RE_STRUCTURAL_SGML.search(stripped):
            has_structural = True
        if "\t" in line.lstrip():
            has_tab = True
        if RE_DOT_LEADER.search(stripped) and RE_PAGE_NUMBER_SUFFIX.search(stripped):
            has_dot_leader = True
        if is_signature_label_line(line):
            has_signature = True
        if RE_SEPARATOR_RUN.search(stripped):
            has_separator = True
        if any(ch.islower() for ch in stripped):
            any_lowercase = True

        content_start = len(line) - len(line.lstrip())
        for match in RE_COLUMN_GAP.finditer(line[: len(line.rstrip())]):
            if match.start() < content_start:
                continue
            max_gap = max(max_gap, len(match.group()))
        gaps = _line_gap_starts(line)
        if gaps:
            gap_start_rows.append(gaps)
        cells = _numeric_cell_starts(line)
        if cells:
            numeric_cell_rows.append(cells)

        letters = sum(ch.isalpha() for ch in stripped)
        alpha_chars += letters
        total_chars += len(stripped)

    alpha_density = alpha_chars / total_chars if total_chars else 0.0
    shared_numeric_columns = _shared_columns(tuple(numeric_cell_rows), min_rows=3)
    return _Features(
        non_blank=non_blank,
        has_structural=has_structural,
        has_tab=has_tab,
        has_separator=has_separator,
        has_dot_leader=has_dot_leader,
        has_signature=has_signature,
        max_gap=max_gap,
        gap_start_rows=tuple(gap_start_rows),
        numeric_cell_rows=tuple(numeric_cell_rows),
        shared_numeric_columns=shared_numeric_columns,
        alpha_density=alpha_density,
        any_lowercase=any_lowercase,
    )


__all__ = [
    "_Features",
    "_compute_features",
    "_line_gap_starts",
    "_numeric_cell_starts",
    "_shared_columns",
]
