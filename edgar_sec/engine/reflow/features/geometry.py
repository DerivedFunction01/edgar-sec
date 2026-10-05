"""Single-pass layout geometry for a block of ASCII lines.
Answers both questions a reflow must ask before touching a block - does it carry column geometry, do its numeric cells line up under shared columns - without building the full feature context, so the resolver can run it on spans it is about to reject.
"""

from __future__ import annotations

from dataclasses import dataclass

from edgar_sec.engine.document.page_markers.signatures import is_signature_label_line
from edgar_sec.engine.tables.tokens import numeric_cell_starts
from edgar_sec.foundation.text.patterns import (
    RE_COLUMN_GAP,
    RE_DOT_LEADER,
    RE_PAGE_NUMBER_SUFFIX,
    RE_SEPARATOR_RUN,
    RE_STRUCTURAL_SGML,
)


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
    numeric_cell_rows: tuple[tuple[int, ...], ...]
    shared_numeric_columns: int
    alpha_density: float
    any_lowercase: bool


def _line_gap_starts(line: str) -> tuple[int, ...]:
    """Positions of internal whitespace runs that separate layout columns.
    Leading indentation is not a gap: indented prose and list items are eligible for unwrapping.
    """
    stripped_end = len(line.rstrip())
    content_start = len(line) - len(line.lstrip())
    starts: list[int] = []
    for match in RE_COLUMN_GAP.finditer(line[:stripped_end]):
        if match.start() < content_start:
            continue
        if (match.end() - match.start()) >= 3:
            starts.append(match.start())
    return tuple(starts)


_numeric_cell_starts = numeric_cell_starts


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
        if any(map(str.islower, stripped)):
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

        letters = sum(map(str.isalpha, stripped))
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


def fast_detect_prose_measure(
    lines: list[str] | tuple[str, ...],
    body_start_line: int = 0,
    scan_window: int = 250,
    target_sample_size: int = 40,
) -> int:
    """Detect document prose width using a shallow early-exit sample."""
    sample: list[int] = []
    limit = min(len(lines), body_start_line + scan_window)

    for i in range(body_start_line, limit):
        line = lines[i].rstrip()
        length = len(line)
        if length < 25 or " " not in line:
            continue

        words = line.split()
        if len(words) >= 4 and sum(1 for c in line if c.isalpha()) >= length * 0.5:
            sample.append(length)

            if len(sample) == 20:
                if sum(1 for l in sample if 72 <= l <= 80) >= 15:
                    return 80
                counts: dict[int, int] = {}
                for l in sample:
                    counts[l] = counts.get(l, 0) + 1
                top_len, freq = max(counts.items(), key=lambda kv: kv[1])
                if freq >= 10:
                    return top_len

            if len(sample) >= target_sample_size:
                break

    if len(sample) < 10:
        return 80

    counts = {}
    for l in sample:
        counts[l] = counts.get(l, 0) + 1
    top_len, freq = max(counts.items(), key=lambda kv: kv[1])
    if freq >= 10:
        return top_len

    sorted_sample = sorted(sample)
    p80 = sorted_sample[int(len(sorted_sample) * 0.80)]
    return 80 if 72 <= p80 <= 80 else p80


__all__ = [
    "_Features",
    "_compute_features",
    "_line_gap_starts",
    "_numeric_cell_starts",
    "_shared_columns",
    "fast_detect_prose_measure",
]
