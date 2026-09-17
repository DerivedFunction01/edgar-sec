"""Post-table extraction cleanup and false/layout table unwrapping.

The default :func:`cleanup_false_tables` pass unwraps the dominant
layout-only HTML table cases: a rendered ``<TABLE>`` block whose visible
text fits on a single line (often a single bulleted risk-factor row, a
checkbox row, or a one-line prose fragment) rather than a structured
multi-line table. Consecutive unwrapped tables join onto a single
separated line, with a single newline between bullet/list items so they
remain readable as a list rather than collapsing into a single sentence
or producing extra blank lines.

Tables are intentionally retained when:
 * they have more than one visible text line (multi-row financial
   statements, multi-cell data tables, signatory blocks, etc.);
 * their visible text matches a table-of-contents row with page numbers or
   dot leaders; or
 * the rendered text contains only numeric separator characters
   (financial-statement-like layouts).
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import TYPE_CHECKING

from defs.sec_forms.cover.structure import RE_ITEM_REFERENCE, RE_PART_REFERENCE
from defs.sec_forms.cover.toc import looks_like_toc_row, looks_like_toc_tabular
from defs.tables.patterns import FOOTNOTE_RE
from defs.text.patterns import roman_to_int
from defs.text.tokens import BULLET_MARKER_RE, is_list_or_bullet_marker

from .numeric_cells import is_numeric_cell

if TYPE_CHECKING:
    from defs.tables.ascii_html import TableGeometry

_RE_TABLE_BLOCK = re.compile(r"<TABLE>.*?</TABLE>", re.DOTALL)
_RE_NUMERIC_SEPARATOR = re.compile(r"^[-=\s]+$")
_RE_ORDERED_MARKER = re.compile(
    r"^(?:(?P<number>\d{1,3})\s*[.)]\s*"
    r"|(?P<roman>[ivxlcdm]+)\s*[.)]\s*"
    r"|(?P<letter>[a-z])\s*[.)]\s*)",
    re.IGNORECASE,
)
_RE_WRAPPED_MARKER = re.compile(
    r"^\(\s*(?P<token>\d{1,3}|[ivxlcdm]+|[a-z])\s*\)\s*",
    re.IGNORECASE,
)
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
    match = _RE_ORDERED_MARKER.match(value)
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
    match = _RE_WRAPPED_MARKER.match(value)
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
        rows.append([(family, value) for family, value, _ in candidates])

    has_plain_letter = any(
        len(candidates) == 1 and candidates[0][0] == "letter" for candidates in rows
    )
    has_wide_roman = any(
        len(candidates) == 1 and candidates[0][0] == "roman" for candidates in rows
    )
    # Letters stay letters: when unambiguous letter rows exist, ambiguous
    # single characters (``i)``, ``v)`` ...) must read as letters, never roman.
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
            bool(_RE_ORDERED_MARKER.match(cell)) for cell in non_empty_first
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


def _is_list_item(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    first_token = stripped.split(maxsplit=1)[0]
    return bool(BULLET_MARKER_RE.match(first_token))


def _join_prose_rows(rows: list[list[str]]) -> str:
    """Join logical prose rows, breaking after complete list items."""
    texts = [" ".join(row) for row in rows]
    pieces: list[str] = []
    for index, text in enumerate(texts):
        if index > 0:
            previous = texts[index - 1].rstrip()
            pieces.append("\n" if previous.endswith((".", ";", ":", "!", "?")) else " ")
        pieces.append(text)
    return "".join(pieces)


def unwrap_grid(grid_rows: Sequence[Sequence[str]]) -> str:
    """Unwrap a false grid into formatted prose or bullet text."""
    rows = [[cell.strip() for cell in row if cell.strip()] for row in grid_rows]
    rows = [row for row in rows if row]
    if not rows:
        return ""
    has_bullets = any(BULLET_MARKER_RE.match(cell) for row in rows for cell in row)
    has_ordered = any(_marker_candidates(cell) for row in rows for cell in row)
    if has_bullets or has_ordered:
        return "\n".join(" ".join(row) for row in rows)
    return _join_prose_rows(rows)


def _unwrap_block(block: str, geometry: TableGeometry | None = None) -> str:
    if geometry is not None and geometry.rows:
        return unwrap_grid(geometry.rows)
    return _visible_text(block)


def cleanup_false_tables_with_metadata(
    text: str,
    geometries: Sequence[TableGeometry] | None = None,
) -> tuple[str, tuple[TableGeometry, ...]]:
    """Unwrap layout-only single-line tables without dropping surrounding text."""
    if "<TABLE>" not in text:
        return text, tuple(geometries or ())

    matches = list(_RE_TABLE_BLOCK.finditer(text))
    if not matches:
        return text, tuple(geometries or ())

    blocks = [m.group(0) for m in matches]
    verdicts = [
        is_false_table(
            block, geometries[i] if geometries and i < len(geometries) else None
        )
        for i, block in enumerate(blocks)
    ]
    # A footnote-like table that immediately precedes a retained table may
    # unwrap even when its second-column text is label-shaped.
    for i, unwrapped in enumerate(verdicts):
        if unwrapped or i + 1 >= len(blocks) or verdicts[i + 1]:
            continue
        if text[matches[i].end() : matches[i + 1].start()].strip():
            continue
        geometry = geometries[i] if geometries and i < len(geometries) else None
        if (
            geometry is not None
            and geometry.rows
            and is_false_table(blocks[i], geometry, allow_footnote_context=True)
        ):
            verdicts[i] = True

    kept_geometries = tuple(
        geometry
        for index, geometry in enumerate(geometries or ())
        if index >= len(blocks) or not verdicts[index]
    )

    if not any(verdicts):
        return text, kept_geometries

    pieces: list[str] = []
    last = 0
    previous_unwrapped: str | None = None

    for i, match in enumerate(matches):
        gap = text[last : match.start()]
        if not verdicts[i]:
            pieces.append(gap)
            pieces.append(match.group(0))
            previous_unwrapped = None
            last = match.end()
            continue

        geometry = geometries[i] if geometries and i < len(geometries) else None
        unwrapped = _unwrap_block(match.group(0), geometry)

        if previous_unwrapped is not None and not gap.strip():
            if _is_list_item(previous_unwrapped) or _is_list_item(unwrapped):
                if pieces:
                    pieces[-1] = pieces[-1].rstrip()
                pieces.append("\n")
            else:
                if pieces and not pieces[-1].endswith((" ", "\n")):
                    pieces.append(" ")
        else:
            pieces.append(gap)

        pieces.append(unwrapped)
        previous_unwrapped = unwrapped
        last = match.end()

    pieces.append(text[last:])
    return "".join(pieces).strip(), kept_geometries


def cleanup_false_tables(
    text: str,
    geometries: Sequence[TableGeometry] | None = None,
) -> str:
    """Unwrap layout-only tables without exposing metadata details."""
    cleaned, _ = cleanup_false_tables_with_metadata(text, geometries)
    return cleaned


__all__ = [
    "cleanup_false_tables",
    "cleanup_false_tables_with_metadata",
    "is_false_grid",
    "is_false_table",
    "unwrap_grid",
]
