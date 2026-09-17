"""Domain-neutral table continuation detection and pre-render fusion for SEC tables."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from defs.regex import build_alternation
from defs.tables.tokens import (
    ALL_CURRENCY_SYMBOLS,
    is_financial_placeholder,
    is_numeric_cell,
    is_year_token,
)

if TYPE_CHECKING:
    from defs.tables.ascii_html.model import SourceCell, SourceTable

_CONTINUED_TOKENS = build_alternation(
    ["continued", "cont'd", "contd", "continuation"],
    auto_escape=True,
)
_RE_CONTINUED = re.compile(rf"\b(?:{_CONTINUED_TOKENS})\b", re.IGNORECASE)

_RE_PAGE_FURNITURE = re.compile(
    r"<hr\b[^>]*>|"
    r"</?page\b[^>]*>|"
    r"__SEC_PAGE_[A-Z_]+__|"
    r"<table\b[^>]*>.*?</table>",
    re.IGNORECASE | re.DOTALL,
)

_RE_HTML_TAGS = re.compile(r"<[^>]+>")
_RE_NON_WORD = re.compile(r"[^\w\s]")


@dataclass(slots=True)
class ContinuationDecision:
    """Decision on whether table B continues table A and how to fuse them."""

    is_continuation: bool
    header_rows_to_drop: int = 0
    reason: str = ""


def _normalize_cell_for_matching(text: str) -> str:
    """Normalize header text for comparison by stripping continuation markers and punctuation."""
    cleaned = _RE_CONTINUED.sub("", text)
    cleaned = _RE_NON_WORD.sub("", cleaned)
    return " ".join(cleaned.lower().split())


def is_allowed_intervening_content(html_snippet: str) -> bool:
    """Return True if intervening content consists only of page furniture and whitespace.

    Reject immediately if substantial narrative prose exists between the two tables.
    """
    if not html_snippet:
        return True
    stripped_furniture = _RE_PAGE_FURNITURE.sub(" ", html_snippet)
    plain_text = _RE_HTML_TAGS.sub(" ", stripped_furniture)
    normalized = " ".join(plain_text.split())
    if not normalized:
        return True
    # Short page continuation banners or note headers (e.g. "Note 13 (Continued)") are allowed
    return len(normalized) <= 100 and bool(_RE_CONTINUED.search(normalized))


def _is_valid_header_row(row: tuple[SourceCell, ...]) -> bool:
    """Return True if row represents a structural header rather than a numeric data row."""
    cells = [c for c in row if not c.style.is_hidden and c.text.strip()]
    if not cells:
        return False
    if any(c.tag.lower() == "th" for c in cells):
        return True
    for c in cells:
        txt = c.text.strip()
        if txt in ALL_CURRENCY_SYMBOLS or is_financial_placeholder(txt):
            return False
        if is_numeric_cell(txt):
            # Allow isolated 4-digit years in header rows (e.g. 2017, 2018), reject data amounts
            cleaned_num = txt.replace(",", "").strip("()")
            for sym in ALL_CURRENCY_SYMBOLS:
                cleaned_num = cleaned_num.replace(sym, "")
            if not is_year_token(cleaned_num):
                return False
    return True


def _extract_header_signatures(table: SourceTable) -> list[tuple[str, ...]]:
    """Extract normalized header text rows from the top of a SourceTable."""
    headers: list[tuple[str, ...]] = []
    for row in table.rows[:6]:
        if not _is_valid_header_row(row):
            break
        texts = tuple(
            _normalize_cell_for_matching(cell.text)
            for cell in row
            if not cell.style.is_hidden and cell.text.strip()
        )
        texts = tuple(t for t in texts if t)
        if texts:
            headers.append(texts)
    return headers


def detect_table_continuation(
    table_a: SourceTable,
    table_b: SourceTable,
    intervening_html: str = "",
) -> ContinuationDecision:
    """Evaluate whether table B is a high-confidence continuation of table A.

    Applies conservative structural gates:
    1. Intervening content: exclusively page break sentinels/furniture and whitespace.
    2. Minimum size: both tables must be multi-row tables (not single-line signature/date labels).
    3. Column count compatibility: same maximum row width / active columns.
    4. Header compatibility: Table B repeats Table A's header row(s) or has an explicit
       continuation marker, and contains body data rows.
    """
    if len(table_a.rows) < 2 or len(table_b.rows) < 2:
        return ContinuationDecision(
            is_continuation=False,
            reason="Tables must have at least 2 rows for continuation",
        )

    # Gate 1: Fast intervening content check
    if intervening_html and not is_allowed_intervening_content(intervening_html):
        return ContinuationDecision(
            is_continuation=False,
            reason="Substantial text between tables",
        )

    # Gate 2: Column structure check
    span_a = max(len(row) for row in table_a.rows)
    span_b = max(len(row) for row in table_b.rows)
    if span_a != span_b and abs(span_a - span_b) > 1:
        return ContinuationDecision(
            is_continuation=False,
            reason=f"Column count mismatch: {span_a} vs {span_b}",
        )

    # Gate 3: Header signature comparison
    headers_a = _extract_header_signatures(table_a)
    headers_b = _extract_header_signatures(table_b)

    if not headers_a or not headers_b:
        return ContinuationDecision(is_continuation=False, reason="Missing headers")

    # Match leading header rows
    matching_headers = 0
    for h_a, h_b in zip(headers_a, headers_b):
        if h_a == h_b:
            matching_headers += 1
        else:
            break

    if matching_headers > 0 and len(table_b.rows) > matching_headers:
        return ContinuationDecision(
            is_continuation=True,
            header_rows_to_drop=matching_headers,
            reason=f"Matched {matching_headers} header row(s) and body rows present",
        )

    return ContinuationDecision(
        is_continuation=False,
        reason="Headers do not match or table B has no body rows",
    )


def fuse_source_tables(
    table_a: SourceTable,
    table_b: SourceTable,
    header_rows_to_drop: int = 1,
) -> SourceTable:
    """Fuse table B's data rows into table A, adjusting row indices."""
    from defs.tables.ascii_html.model import SourceCell, SourceTable

    merged_rows: list[tuple[SourceCell, ...]] = list(table_a.rows)
    start_r_idx = len(merged_rows)

    rows_to_append = table_b.rows[header_rows_to_drop:]
    for offset, row in enumerate(rows_to_append):
        new_row_idx = start_r_idx + offset
        updated_cells: list[SourceCell] = []
        for cell in row:
            updated_cells.append(
                SourceCell(
                    row_index=new_row_idx,
                    source_col_index=cell.source_col_index,
                    tag=cell.tag,
                    text=cell.text,
                    raw_attributes=cell.raw_attributes,
                    style=cell.style,
                    colspan=cell.colspan,
                    rowspan=cell.rowspan,
                    is_nested_table_holder=cell.is_nested_table_holder,
                    nested_table_index=cell.nested_table_index,
                    indent_spaces=cell.indent_spaces,
                )
            )
        merged_rows.append(tuple(updated_cells))

    return SourceTable(
        table_index=table_a.table_index,
        parent_table_index=table_a.parent_table_index,
        raw_node=table_a.raw_node,
        rows=tuple(merged_rows),
        style=table_a.style,
        attributes=table_a.attributes,
    )


__all__ = [
    "ContinuationDecision",
    "detect_table_continuation",
    "fuse_source_tables",
    "is_allowed_intervening_content",
]
