"""Is this table really a table? False/layout grid classification.

A filing uses HTML tables for things that are not tables: a single bulleted
risk-factor row, an exhibit index, a two-column heading. Converting those to
aligned ASCII destroys them, and leaving them as grids produces noise. This
module answers the question from the resolved grid rather than from the rendered
text, because a layout grid's shape — one marker column beside one prose column
— is the evidence, and rendered wrapping has already destroyed it.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import TYPE_CHECKING

from edgar_sec.foundation.text.tokens import (
    BULLET_MARKER_RE,
    ORDERED_MARKER_PREFIX_RE,
    WRAPPED_MARKER_PREFIX_RE,
    is_list_or_bullet_marker,
    roman_to_int,
)

from ..numeric_cells import is_numeric_cell
from ..patterns import FOOTNOTE_RE
from ..toc.patterns import (
    RE_ITEM_REFERENCE,
    RE_PART_REFERENCE,
    looks_like_toc_row,
    looks_like_toc_tabular,
)

if TYPE_CHECKING:
    from ..ascii_html.model import TableGeometry

_RE_NUMERIC_SEPARATOR = re.compile(r"^[-=\s]+$")
_RE_UNAMBIGUOUS_MARKER = re.compile(r"\[\d{1,3}\]|[\*\†\‡\§\#]+")


def _is_single_column_prose(lines: list[str]) -> bool:
    """Return whether every row carries at least one nonnumeric word."""
    if len(lines) == 1 and is_numeric_cell(lines[0]):
        return True
    return bool(lines) and all(
        any(not is_numeric_cell(word) for word in line.split()) for line in lines
    )


def _is_prose_marker(value: str) -> bool:
    """Return whether a cell is a bullet or footnote marker (numeric allowed)."""
    value = value.strip()
    if not value:
        return False
    if BULLET_MARKER_RE.match(value):
        return True
    return bool(FOOTNOTE_RE.fullmatch(value))


def _is_unambiguous_list_marker(value: str) -> bool:
    """Return whether a marker is an unambiguous bullet or delimited list marker."""
    value = value.strip()
    if not value:
        return False
    if is_list_or_bullet_marker(value):
        return True
    return bool(_RE_UNAMBIGUOUS_MARKER.fullmatch(value))


def _is_prose_text(value: str) -> bool:
    """Return whether a cell reads as prose rather than purely numeric data."""
    value = value.strip()
    if not value:
        return False
    return any(c.isalpha() for c in value) and not is_numeric_cell(value)


def _marker_candidates(value: str) -> list[tuple[str, int, str]]:
    """Return every plausible (family, value, remaining prose) reading of a cell.

    Single characters in ``ivxlcdm`` are ambiguous between roman numerals and
    letter sequences (for example ``i)`` inside ``g) h) i) j) k)``); callers
    resolve the ambiguity consistently across the whole row sequence.
    Parenthesized forms such as ``(1)``, ``(iv)``, and ``(a)`` read the same
    way as their bare ``1.``, ``iv.``, and ``a.`` counterparts.
    """
    value = value.strip()
    match = ORDERED_MARKER_PREFIX_RE.match(value)
    if match is None:
        return _wrapped_marker_candidates(value)
    rest = value[match.end() :].strip()
    if match.group("number"):
        return [("number", int(match.group("number")), rest)]
    if match.group("roman"):
        roman = match.group("roman").lower()
        roman_value = roman_to_int(roman)
        if roman_value is None:
            return []
        candidates = [("roman", roman_value, rest)]
        if len(roman) == 1:
            candidates.append(("letter", ord(roman) - ord("a") + 1, rest))
        return candidates
    letter = match.group("letter").lower()
    candidates = [("letter", ord(letter) - ord("a") + 1, rest)]
    if roman_to_int(letter) is not None:
        candidates.append(("roman", roman_to_int(letter), rest))
    return candidates


def _wrapped_marker_candidates(value: str) -> list[tuple[str, int, str]]:
    """Return marker candidates for a parenthesized ``(1)``/``(iv)``/``(a)`` cell."""
    match = WRAPPED_MARKER_PREFIX_RE.match(value)
    if match is None:
        return []
    token = match.group("token").lower()
    rest = value[match.end() :].strip()
    if token.isdigit():
        return [("number", int(token), rest)]
    roman_value = roman_to_int(token)
    candidates: list[tuple[str, int, str]] = []
    if roman_value is not None:
        candidates.append(("roman", roman_value, rest))
    if len(token) == 1:
        candidates.append(("letter", ord(token) - ord("a") + 1, rest))
    return candidates


def _step_stack(
    stack: list[tuple[str, int]], family: str, value: int
) -> list[tuple[str, int]] | None:
    """Attempt to advance an outline stack with a new (family, value) marker."""
    if not stack:
        return [(family, value)]
    if stack[-1][0] == family:
        if value > stack[-1][1]:
            new_stack = list(stack)
            new_stack[-1] = (family, value)
            return new_stack
        return None
    for i in range(len(stack) - 1, -1, -1):
        if stack[i][0] == family:
            if value > stack[i][1]:
                new_stack = stack[:i]
                new_stack.append((family, value))
                return new_stack
            return None
    if value == 1:
        new_stack = list(stack)
        new_stack.append((family, value))
        return new_stack
    return None


def _passes_monotonic(
    rows: list[list[tuple[str, int]]], prefer: str | None = None
) -> bool:
    """Check monotonic increase (flat or hierarchical) under consistent interpretation."""

    def _search(index: int, stack: list[tuple[str, int]]) -> bool:
        if index >= len(rows):
            return True
        candidates = rows[index]
        if prefer is not None:
            sorted_candidates = sorted(
                candidates, key=lambda c: 0 if c[0] == prefer else 1
            )
        else:
            sorted_candidates = candidates
        for family, value in sorted_candidates:
            next_stack = _step_stack(stack, family, value)
            if next_stack is not None and _search(index + 1, next_stack):
                return True
        return False

    return _search(0, [])


def _is_ordered_prose_grid(grid: list[tuple[str, ...]]) -> bool:
    rows: list[list[tuple[str, int]]] = []
    has_plain_letter = False
    has_wide_roman = False
    for row in grid:
        marker_cells: list[tuple[str, list[tuple[str, int, str]]]] = []
        for cell in row:
            if not cell.strip():
                continue
            candidates = _marker_candidates(cell)
            if candidates:
                marker_cells.append((cell, candidates))
        if len(marker_cells) != 1:
            return False
        marker_cell, candidates = marker_cells[0]
        prose = " ".join(
            cell.strip() for cell in row if cell.strip() and cell is not marker_cell
        )
        rest = candidates[0][2]
        if rest:
            prose = f"{rest} {prose}".strip()
        if not _is_prose_text(prose):
            return False
        if len(candidates) == 1:
            fam = candidates[0][0]
            if fam == "letter":
                has_plain_letter = True
            elif fam == "roman":
                has_wide_roman = True
        rows.append([(family, value) for family, value, _ in candidates])

    if has_plain_letter and _passes_monotonic(rows, "letter"):
        return True
    if has_wide_roman and _passes_monotonic(rows, "roman"):
        return True
    if not has_plain_letter and not has_wide_roman:
        return _passes_monotonic(rows, "letter") or _passes_monotonic(rows, "roman")
    return False


def _visible_text(block: str) -> str:
    inner = block[len("<TABLE>") : -len("</TABLE>")]
    lines = [line.strip() for line in inner.splitlines() if line.strip()]
    return " ".join(lines)


def is_false_grid(
    grid_rows: Sequence[Sequence[str]],
    *,
    allow_footnote_context: bool = False,
) -> bool:
    """Return True for prose-wrapper table grids that should be unwrapped.

    Geometry-aware classification ignores fully-empty spacer rows and columns
    before judging the effective grid shape. ``allow_footnote_context`` relaxes
    the prose-length gate for footnote-marker tables that immediately precede a
    retained table; marker-shape and numeric-content checks still apply.
    """
    grid = [row for row in grid_rows if any(cell.strip() for cell in row)]
    if not grid:
        return True
    span = max(len(row) for row in grid)
    effective = [
        index
        for index in range(span)
        if any(index < len(row) and row[index].strip() for row in grid)
    ]
    lines = [" ".join(cell.strip() for cell in row).strip() for row in grid]
    effective_grid = [tuple(row[index] for index in effective) for row in grid]
    if len(effective) > 2:
        return _is_ordered_prose_grid(effective_grid)

    if len(effective) == 2:
        if _is_ordered_prose_grid(effective_grid):
            return True
        first_column = [row[effective[0]].strip() for row in grid]
        second_column = [
            row[effective[1]].strip() if effective[1] < len(row) else "" for row in grid
        ]
        if all(
            RE_ITEM_REFERENCE.match(cell) or RE_PART_REFERENCE.match(cell)
            for cell in first_column
        ):
            if any(is_numeric_cell(cell) for cell in second_column if cell):
                return False
            return not any(
                looks_like_toc_row(" ".join(row))
                or looks_like_toc_tabular(" ".join(row))
                for row in grid
            )
        non_empty_first = [cell for cell in first_column if cell]
        if non_empty_first and all(
            bool(ORDERED_MARKER_PREFIX_RE.match(cell)) for cell in non_empty_first
        ):
            if any(is_numeric_cell(cell) for cell in second_column if cell):
                return False
            return not any(
                looks_like_toc_row(" ".join(row))
                or looks_like_toc_tabular(" ".join(row))
                for row in grid
            )
        # Check for standard bullet rows or lead-in prose row + bullet rows
        non_empty_first = [cell for cell in first_column if cell]
        if non_empty_first and all(_is_prose_marker(cell) for cell in non_empty_first):
            if any(is_numeric_cell(cell) for cell in second_column if cell):
                return False
            if not all(_is_prose_text(cell) for cell in second_column if cell):
                return False
        elif (
            len(first_column) >= 2
            and first_column[0]
            and not second_column[0]
            and _is_prose_text(first_column[0])
            and (
                first_column[0].rstrip().endswith(":")
                or len(first_column[0].split()) >= 3
            )
            and not is_numeric_cell(first_column[0])
            and not looks_like_toc_row(first_column[0])
        ):
            rem_first = [cell for cell in first_column[1:] if cell]
            rem_second = [cell for cell in second_column[1:] if cell]
            if (
                not rem_first
                or not all(_is_unambiguous_list_marker(cell) for cell in rem_first)
                or any(is_numeric_cell(cell) for cell in rem_second)
                or not all(_is_prose_text(cell) for cell in rem_second)
            ):
                return False
        else:
            return False
    elif not _is_single_column_prose(lines) or any(
        looks_like_toc_row(line) or looks_like_toc_tabular(line) for line in lines
    ):
        return False
    return True


def is_false_table(
    table_body: str,
    geometry: TableGeometry | None = None,
    *,
    allow_footnote_context: bool = False,
) -> bool:
    """Return True for prose-wrapper tables that should be unwrapped."""
    if geometry is not None and geometry.rows:
        return is_false_grid(
            geometry.rows, allow_footnote_context=allow_footnote_context
        )
    inner = table_body[len("<TABLE>") : -len("</TABLE>")]
    lines = [line.strip() for line in inner.splitlines() if line.strip()]
    if not lines:
        return True
    if len(lines) != 1:
        return False
    text = lines[0]
    if not text:
        return True

    if (RE_PART_REFERENCE.match(text) or RE_ITEM_REFERENCE.match(text)) and (
        looks_like_toc_row(text) or looks_like_toc_tabular(text)
    ):
        return False
    return not _RE_NUMERIC_SEPARATOR.match(text)


__all__ = [
    "is_false_grid",
    "is_false_table",
]
