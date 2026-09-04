"""Scoped template repair for SEC Item 15/16 Exhibit Index tables."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from defs.regex import build_alternation
from defs.sec_forms.families import resolve_alias
from defs.tables.builder import HTMLTableConverter
from defs.text.dates import parse_date
from defs.text.tokens import FOOTNOTE_MARKER_RE

if TYPE_CHECKING:
    from defs.sec_forms.context import SectionContext

EXHIBIT_INDEX_STATUTORY_PHRASES: dict[str, tuple[str, ...]] = {
    "P1_exhibit_number": (
        "exhibit number",
        "exhibit no.",
        "exhibit no",
        "exhibit",
    ),
    "P2_description": (
        "exhibit description",
        "description of exhibit",
        "description of exhibits",
        "title of document",
    ),
    "P3_incorporated": (
        "incorporated by reference",
        "incorporation by reference",
        "incorporated herein by reference",
    ),
    "P4_filed_herewith": (
        "filed herewith",
        "furnished herewith",
        "filed / furnished herewith",
        "filed/furnished herewith",
    ),
    "P5_filing_date": (
        "filing date",
        "date of filing",
    ),
}

_EXHIBIT_HEADER_MAX_WORDS = 6

_EXHIBIT_ID_PATTERNS = [
    r"\(?\d+\)?(?:\.\d+)*(?:\([a-z0-9]+\))?[*+†‡§u]*",
    r"\d{3}\*{1,2}",
    r"\d+\.[A-Z]+",
    r"EX-\d+\.[A-Z]+",
]
_EXHIBIT_ID_RE = re.compile(
    rf"^(?:{build_alternation(_EXHIBIT_ID_PATTERNS, auto_escape=False)})$",
    re.IGNORECASE,
)

_ADDITIONAL_FORMS = frozenset(
    {"DEF 14A", "DEF14A", "S-8", "S-3", "S-1", "S-4", "SC 13G", "SC 13D"}
)

_INDICATOR_RE = re.compile(r"^[Xx*✓+†‡§u•]$|^Yes$", re.IGNORECASE)
_FILE_NO_RE = re.compile(r"^\d{1,3}-\d{4,8}(?:-[A-Z0-9]+)?$")


def _is_date_token(value: str) -> bool:
    """Check if value is a recognized calendar date string."""
    val = value.strip()
    return bool(val and parse_date(val))


def _is_form_token(value: str) -> bool:
    """Check if value is a recognized SEC form token."""
    val = value.strip()
    if not val:
        return False
    clean = val.removeprefix("Form ").removeprefix("FORM ").strip().upper()
    return bool(resolve_alias(clean) or clean in _ADDITIONAL_FORMS)


def _is_indicator_token(value: str) -> bool:
    """Check if value is a standalone 'filed herewith' checkmark or indicator."""
    return bool(_INDICATOR_RE.fullmatch(value.strip()))


def _is_file_number(value: str) -> bool:
    """Check if value is an SEC Commission file number (e.g. 001-36743)."""
    return bool(_FILE_NO_RE.fullmatch(value.strip()))


def _matches_multi_column_exhibit_header(grid: list[list[str]]) -> tuple[bool, int]:
    """Check if table has a multi-column exhibit index header structure with column drift."""
    if len(grid) < 3:
        return False, 0
    header_rows = grid[: min(4, len(grid))]
    header_text = " ".join(c.lower() for r in header_rows for c in r if c.strip())

    phrase_matches = 0
    for alternatives in EXHIBIT_INDEX_STATUTORY_PHRASES.values():
        if any(alt in header_text for alt in alternatives):
            phrase_matches += 1

    if phrase_matches < 2:
        return False, 0

    # Determine header row count
    header_count = 1
    for idx, row in enumerate(grid[:4]):
        cells = [c.strip() for c in row if c.strip()]
        if not cells:
            continue
        first = cells[0].split(maxsplit=1)[0]
        if _EXHIBIT_ID_RE.fullmatch(first):
            header_count = idx
            break
        if any(
            alt in " ".join(cells).lower()
            for alt in ("form", "period ending", "filing date", "filed herewith")
        ):
            header_count = idx + 1

    header_cols_count = max(
        (len([c for c in r if c.strip()]) for r in grid[:header_count]), default=0
    )
    if header_cols_count <= 2:
        return False, 0

    # Only apply multi-column alignment when rows exhibit column count variations / drift
    ref_row_lengths = set()
    for row in grid[header_count:]:
        cells = [c.strip() for c in row if c.strip()]
        if len(cells) > 2 and _EXHIBIT_ID_RE.fullmatch(cells[0].split(maxsplit=1)[0]):
            ref_row_lengths.add(len(cells))

    needs_alignment = len(ref_row_lengths) > 1 or any(
        length < header_cols_count for length in ref_row_lengths
    )
    if not needs_alignment:
        return False, 0

    return True, max(1, header_count)


def _align_multi_column_exhibit_row(
    cells: list[str], has_filed_herewith: bool, has_inc_ref: bool
) -> list[str]:
    """Align a single data row's extracted cells into canonical exhibit slots."""
    if not cells:
        return []

    exhibit_num = cells[0]
    if len(cells) == 1:
        return [exhibit_num, "", "", "", "", "", ""]

    exhibit_desc = cells[1]
    remaining = cells[2:]

    filed_herewith = ""
    form_val = ""
    period_ending = ""
    ref_exhibit = ""
    filing_date = ""

    # Check if first trailing item is an indicator (e.g. 'X')
    if remaining and _is_indicator_token(remaining[0]) and len(remaining) == 1:
        filed_herewith = remaining[0]
        remaining = []
    elif (
        remaining
        and _is_indicator_token(remaining[0])
        and not _is_form_token(remaining[0])
    ):
        filed_herewith = remaining[0]
        remaining = remaining[1:]

    # Parse remaining reference tokens
    if remaining:
        # Check if first is form token
        if _is_form_token(remaining[0]):
            form_val = remaining[0]
            ref_tokens = remaining[1:]
        else:
            ref_tokens = remaining

        dates = [t for t in ref_tokens if _is_date_token(t)]
        file_nos = [t for t in ref_tokens if _is_file_number(t)]
        others = [
            t for t in ref_tokens if not _is_date_token(t) and not _is_file_number(t)
        ]

        if len(dates) >= 2:
            period_ending = dates[0]
            filing_date = dates[1]
            if others:
                ref_exhibit = others[0]
        elif len(dates) == 1:
            filing_date = dates[0]
            if file_nos:
                period_ending = file_nos[0]
            elif others:
                ref_exhibit = others[0]
        elif file_nos and others:
            period_ending = file_nos[0]
            ref_exhibit = others[0]
        elif others:
            ref_exhibit = others[0]

    return [
        exhibit_num,
        exhibit_desc,
        filed_herewith,
        form_val,
        period_ending,
        ref_exhibit,
        filing_date,
    ]


def _render_multi_column_exhibit_index(
    source_grid: list[list[str]], header_count: int
) -> str | None:
    """Format and build multi-column exhibit index schedule."""
    # Build canonical header rows
    canon_headers = [
        "Exhibit Number",
        "Exhibit Description",
        "Filed Herewith",
        "Form",
        "Period Ending",
        "Exhibit",
        "Filing Date",
    ]
    raw_data_rows = source_grid[header_count:]
    aligned_rows = []

    for row in raw_data_rows:
        cells = [c.strip() for c in row if c.strip()]
        if not cells:
            continue
        first = cells[0].split(maxsplit=1)[0]
        if not _EXHIBIT_ID_RE.fullmatch(first) and len(cells) == 1:
            # Continuation text for description
            if aligned_rows:
                aligned_rows[-1][1] += f" {cells[0]}"
            continue
        aligned = _align_multi_column_exhibit_row(
            cells, has_filed_herewith=True, has_inc_ref=True
        )
        if aligned:
            aligned_rows.append(aligned)

    if not aligned_rows:
        return None

    # Check which columns are actually populated
    used_cols = [
        c
        for c in range(len(canon_headers))
        if any(row[c].strip() for row in aligned_rows)
    ]
    if len(used_cols) < 3:
        return None

    final_headers = [
        [canon_headers[c] for c in used_cols],
    ]
    final_data = [[row[c] for c in used_cols] for row in aligned_rows]
    final_grid = final_headers + final_data

    return (
        HTMLTableConverter(grid=final_grid, header_row_count=1)
        .to_generic_table()
        .build()
    )


def _render_compact_exhibit_index(source_grid: list[list[str]]) -> str | None:
    """Render continuation rows from a two-column exhibit index as data."""
    if len(source_grid) < 3:
        return None
    compact = [[cell for cell in row if cell.strip()] for row in source_grid]
    compact = [
        [row[0] + " " + row[1], *row[2:]]
        if len(row) >= 3 and FOOTNOTE_MARKER_RE.fullmatch(row[1])
        else row
        for row in compact
    ]
    header_count = 0
    for index, row in enumerate(compact[:3]):
        if (
            len(row) >= 2
            and "exhibit" in row[0].casefold()
            and "description" in row[1].casefold()
            and len(row[1].split()) <= _EXHIBIT_HEADER_MAX_WORDS
        ):
            header_count = index + 1
            if (
                index + 1 < len(compact)
                and len(compact[index + 1]) >= 2
                and compact[index + 1][0].casefold() == "form"
                and compact[index + 1][1].casefold() == "date"
            ):
                header_count += 1
            break
    if header_count == 0 and max((len(row) for row in compact), default=0) > 2:
        return None
    exhibit_rows = compact[header_count:]
    minimum_exhibits = (
        1 if header_count >= 2 and "incorporated" in compact[0][0].casefold() else 3
    )
    if (
        sum(
            bool(_EXHIBIT_ID_RE.fullmatch(row[0].split(maxsplit=1)[0]))
            for row in exhibit_rows
            if row
        )
        < minimum_exhibits
    ):
        return None
    width = max((len(row) for row in compact), default=0)
    rows = [row + [""] * (width - len(row)) for row in compact]
    return (
        HTMLTableConverter(grid=rows, header_row_count=header_count)
        .to_generic_table()
        .build()
    )


def exhibit_index_template(
    source_grid: list[list[str]],
    *,
    section_context: SectionContext | None = None,
) -> str | None:
    """Repair and project Exhibit Index tables into canonical columns."""
    _ = section_context
    if len(source_grid) < 3:
        return None

    # 1. Try multi-column structured exhibit index
    is_multi, header_count = _matches_multi_column_exhibit_header(source_grid)
    if is_multi and header_count > 0:
        res = _render_multi_column_exhibit_index(source_grid, header_count)
        if res:
            return res

    # 2. Try compact 2-column exhibit index
    return _render_compact_exhibit_index(source_grid)


__all__ = [
    "exhibit_index_template",
]
