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
 * their visible text starts with ``ITEM `` or ``PART `` (cover/TOC
   detection still uses them); or
 * the rendered text contains only numeric separator characters
   (financial-statement-like layouts).
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import TYPE_CHECKING

from defs.sec_forms.cover.structure import RE_ITEM_REFERENCE, RE_PART_REFERENCE
from defs.tables.patterns import FOOTNOTE_RE
from defs.text.patterns import roman_to_int
from defs.text.tokens import BULLET_MARKER_RE

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


def _is_clear_bullet(value: str) -> bool:
    """Return whether a marker is an unambiguous bullet, not a numeric label."""
    value = value.strip()
    if not value or re.fullmatch(r"\(?\d{1,2}[.)]?", value):
        return False
    return bool(BULLET_MARKER_RE.match(value))


def _is_prose_text(value: str) -> bool:
    """Return whether a cell reads as sentence-like prose rather than a label."""
    value = value.strip()
    if not value:
        return False
    return len(value.split()) >= 6 or len(value) >= 35


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


def _passes_monotonic(rows: list[list[tuple[str, int]]], prefer: str) -> bool:
    """Check strict per-family increase under one consistent interpretation."""
    previous: dict[str, int] = {}
    for candidates in rows:
        chosen: tuple[str, int] | None = None
        if len(candidates) == 1:
            chosen = candidates[0]
        else:
            for family, value in candidates:
                if family == prefer:
                    chosen = (family, value)
                    break
            if chosen is None:
                chosen = candidates[0]
        family, value = chosen
        if family in previous and value <= previous[family]:
            return False
        previous[family] = value
    return True


def _is_ordered_prose_grid(grid: list[tuple[str, ...]]) -> bool:
    rows: list[list[tuple[str, int]]] = []
    for row in grid:
        marker_cells = [
            (cell, _marker_candidates(cell)) for cell in row if _marker_candidates(cell)
        ]
        if len(marker_cells) != 1:
            return False
        marker_cell, candidates = marker_cells[0]
        if not candidates:
            return False
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


def is_false_table(
    table_body: str,
    geometry: TableGeometry | None = None,
    *,
    allow_footnote_context: bool = False,
) -> bool:
    """Return True for prose-wrapper tables that should be unwrapped.

    Geometry-aware classification ignores fully-empty spacer rows and columns
    before judging the effective grid shape. ``allow_footnote_context`` relaxes
    the prose-length gate for footnote-marker tables that immediately precede a
    retained table; marker-shape and numeric-content checks still apply.
    """
    if geometry is not None and geometry.rows:
        grid = [row for row in geometry.rows if any(cell.strip() for cell in row)]
        if not grid:
            return False
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
                row[effective[1]].strip() if effective[1] < len(row) else ""
                for row in grid
            ]
            if not all(_is_prose_marker(cell) for cell in first_column):
                return False
            if any(is_numeric_cell(cell) for cell in second_column if cell):
                return False
            # Numeric/footnote markers are ambiguous with exhibit indexes;
            # require sentence-like prose unless every marker is a clear
            # bullet or the table directly precedes a retained table.
            if (
                not allow_footnote_context
                and not all(_is_clear_bullet(cell) for cell in first_column)
                and not all(_is_prose_text(cell) for cell in second_column)
            ):
                return False
        elif not _is_single_column_prose(lines):
            return False
        return True
    else:
        inner = table_body[len("<TABLE>") : -len("</TABLE>")]
        lines = [line.strip() for line in inner.splitlines() if line.strip()]
    if len(lines) != 1:
        return False
    text = lines[0]
    if not text:
        return False
    if RE_PART_REFERENCE.match(text) or RE_ITEM_REFERENCE.match(text):
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


def _unwrap_block(block: str, geometry: TableGeometry | None = None) -> str:
    if geometry is not None and geometry.rows:
        rows = [[cell.strip() for cell in row if cell.strip()] for row in geometry.rows]
        rows = [row for row in rows if row]
        has_bullets = any(BULLET_MARKER_RE.match(cell) for row in rows for cell in row)
        has_ordered = any(_marker_candidates(cell) for row in rows for cell in row)
        if has_bullets or has_ordered:
            return "\n".join(" ".join(row) for row in rows)
        return _join_prose_rows(rows)
    return _visible_text(block)


def cleanup_false_tables_with_metadata(
    text: str,
    geometries: Sequence[TableGeometry] | None = None,
) -> tuple[str, tuple[TableGeometry, ...]]:
    """Unwrap layout-only single-line tables without dropping surrounding text."""
    blocks = _RE_TABLE_BLOCK.findall(text)
    matches = list(_RE_TABLE_BLOCK.finditer(text))
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
    if "<TABLE>" not in text:
        return text, kept_geometries

    replacements: dict[str, str] = {}
    for index, block in enumerate(blocks):
        if verdicts[index]:
            geometry = (
                geometries[index] if geometries and index < len(geometries) else None
            )
            replacements[block] = _unwrap_block(block, geometry)

    if not replacements:
        return text, kept_geometries

    pattern = re.compile(
        "|".join(re.escape(block) for block in replacements), re.DOTALL
    )
    pieces: list[str] = []
    last = 0
    previous_unwrapped: str | None = None

    for match in pattern.finditer(text):
        gap = text[last : match.start()]
        block = match.group(0)
        unwrapped = replacements[block]

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
    "is_false_table",
]
