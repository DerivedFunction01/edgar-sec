"""Generic text-based ASCII/SGML table layout builder and HTML grid converter."""

from __future__ import annotations

import re
import sys
import warnings
from typing import TYPE_CHECKING

from bs4 import BeautifulSoup, Comment, FeatureNotFound, XMLParsedAsHTMLWarning

# Parsed as HTML for table layout; silence the bs4 XML warning.
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

from .builder import GenericTable, HTMLTableConverter
from .grid_repairs import SpanGroup, apply_grid_repairs
from .patterns import (
    HIDDEN_ELEMENT_STYLE_RE,
    NUMERIC_PERCENT_SPACE_RE,
    PAREN_SPACES_RE,
    UNITS_LABEL_RE,
    YEAR_TOKEN_RE,
)
from .templates import (
    TableScope,
    apply_table_templates,
    bullet_list_template,
    cell_text,
    oriented_prose_fallback,
    row_aware_fallback,
    signature_template,
    span_grid,
)
from .tokens import PREFIX_SYMBOLS, SUFFIX_TOKENS, is_numeric_cell

if TYPE_CHECKING:
    from defs.sec_forms.context import HtmlStructureIndex, SectionContext, TableContext

_BORDER_PROPERTY_RE = re.compile(r"(?:^|;)border-(top|bottom):([^;]*)", re.IGNORECASE)
_TOTAL_LABEL_RE = re.compile(r"\b(?:sub)?total\b", re.IGNORECASE)


def _has_border(cell: object, side: str) -> bool:
    """Return whether an inline border declaration exists for a cell side."""
    style = re.sub(r"\s+", "", cell.get("style", ""))
    return any(
        match_side.casefold() == side
        for match_side, _ in _BORDER_PROPERTY_RE.findall(style)
    )


def _detect_border_header_count(table: object, row_count: int) -> int:
    """Infer a header boundary from the first inline border transition."""
    if row_count < 2:
        return 0
    filtered_rows = [
        row for row in table.find_all("tr") if row.get_text(" ", strip=True)
    ]
    if not filtered_rows:
        return 0

    for row_index, row in enumerate(filtered_rows):
        cells = row.find_all(["td", "th"])
        has_top = any(_has_border(cell, "top") for cell in cells)
        has_bottom = any(_has_border(cell, "bottom") for cell in cells)
        if has_top and has_bottom:
            return 0
        if has_top:
            candidate = row_index
        elif has_bottom:
            candidate = row_index + 1
        else:
            continue
        first_value = next(
            (
                cell.get_text(" ", strip=True)
                for cell in cells
                if cell.get_text(strip=True)
            ),
            "",
        )
        if _TOTAL_LABEL_RE.search(first_value):
            return 0
        return candidate if 0 < candidate < row_count else 0
    return 0


def _detect_explicit_header_count(table: object, row_count: int) -> int:
    """Count leading non-empty rows containing explicit ``th`` cells."""
    filtered_rows = [
        row for row in table.find_all("tr") if row.get_text(" ", strip=True)
    ]
    count = 0
    for row in filtered_rows:
        if not row.find("th"):
            break
        count += 1
    return count if 0 < count < row_count else 0


def _detect_header_like_first_row(table: object, row_count: int) -> int:
    """Weak final fallback: treat the first multi-cell text row as a header."""
    filtered_rows = [
        row for row in table.find_all("tr") if row.get_text(" ", strip=True)
    ]
    for row in filtered_rows[:2]:
        cells = [
            cell.get_text(" ", strip=True)
            for cell in row.find_all(["td", "th"])
            if cell.get_text(strip=True)
        ]
        if len(cells) >= 2 and all(
            not is_numeric_cell(cell) and len(cell) <= 40 for cell in cells
        ):
            return 1
    return 0


def _toc_starts_with_part_heading(
    source_grid: list[list[str]], scope: TableScope
) -> int | None:
    """Keep a leading PART heading in the TOC body rather than as a header."""
    from .toc import PART_HEADING_RE, toc_part_headings_are_body_rows

    if not toc_part_headings_are_body_rows(source_grid, is_toc=scope is TableScope.TOC):
        return None
    first_row = next(
        (row for row in source_grid if any(value.strip() for value in row)), []
    )
    values = [value.strip() for value in first_row if value.strip()]
    if (
        len(values) <= 2
        and (len(values) == 1 or values[1].casefold() in {"page", "pages"})
        and bool(PART_HEADING_RE.fullmatch(values[0]))
    ):
        return 0
    second_row = next(
        (row for row in source_grid[1:] if any(value.strip() for value in row)), []
    )
    second_values = [value.strip() for value in second_row if value.strip()]
    if (
        len(values) == 1
        and values[0].casefold() in {"page", "pages"}
        and second_values
        and PART_HEADING_RE.fullmatch(second_values[0])
    ):
        return 1
    return None


def _detect_section_row_indexes(
    table: object, source_grid: list[list[str]], header_count: int
) -> set[int]:
    """Find visually marked, nonnumeric rows that introduce a table section."""
    styled_rows = [row for row in table.find_all("tr") if row.get_text(" ", strip=True)]
    section_rows: set[int] = set()
    for index, row in enumerate(source_grid):
        if index < header_count or index >= len(styled_rows):
            continue
        values = [value.strip() for value in row if value.strip()]
        if len(values) != 1 or is_numeric_cell(values[0]):
            continue
        cells = styled_rows[index].find_all(["td", "th"])
        if not cells:
            continue
        first_cell = next((cell for cell in cells if cell.get_text(strip=True)), None)
        if first_cell is None:
            continue
        style = re.sub(r"\s+", "", first_cell.get("style", "")).casefold()
        emphasized = bool(
            first_cell.find(["b", "strong", "i", "em"])
            or re.search(r"font-(?:weight:\s*700|style:\s*italic)", style)
        )
        if "border-top:" in style or "border-bottom:" in style or emphasized:
            section_rows.add(index)
    return section_rows


def _detect_section_rows(
    table: object, source_grid: list[list[str]], header_count: int
) -> dict[int, int]:
    section_rows = _detect_section_row_indexes(table, source_grid, header_count)
    styled_rows = [row for row in table.find_all("tr") if row.get_text(" ", strip=True)]
    levels: dict[int, int] = {}
    for index in sorted(section_rows):
        levels[index] = 1 if index - 1 in section_rows else 0
    active_level = 0
    active_label = ""
    active_section = False
    for index in range(header_count, len(source_grid)):
        if index in section_rows:
            active_level = levels[index]
            active_section = True
            active_label = next(
                value.strip() for value in source_grid[index] if value.strip()
            ).casefold()
            continue
        values = [value.strip() for value in source_grid[index] if value.strip()]
        if not values:
            continue
        label = values[0].casefold()
        if not active_section:
            continue
        levels[index] = active_level + 1
        if active_level > 0 and label.startswith("total ") and active_label:
            levels[index] = active_level + 1
            active_level = 0
            active_label = ""
    paddings: dict[int, float] = {}
    for index, row in enumerate(styled_rows[: len(source_grid)]):
        first_cell = next(
            (cell for cell in row.find_all(["td", "th"]) if cell.get_text(strip=True)),
            None,
        )
        if first_cell is None:
            continue
        style = first_cell.get("style", "")
        match = re.search(r"padding-left:\s*([0-9.]+)pt", style)
        if match is None:
            padding = re.search(r"padding:\s*([^;]+)", style)
            if padding:
                vals = padding.group(1).split()
                left = (
                    vals[-1]
                    if len(vals) == 4
                    else vals[1]
                    if len(vals) >= 2
                    else vals[0]
                )
                match = re.fullmatch(r"([0-9.]+)pt", left)
        if match:
            padding_left = float(match.group(1))
            indent = re.search(r"text-indent:\s*(-?[0-9.]+)pt", style)
            paddings[index] = (
                padding_left + float(indent.group(1)) if indent else padding_left
            )
    if paddings:
        clusters: list[list[float]] = []
        for value in sorted(set(paddings.values())):
            if not clusters or value - clusters[-1][-1] > 2.0:
                clusters.append([value])
            else:
                clusters[-1].append(value)
        baseline = min(sum(cluster) / len(cluster) for cluster in clusters)
        deltas = sorted(
            delta
            for delta in {round(value - baseline, 3) for value in paddings.values()}
            if delta > 0
        )
        min_step = 2.0
        real_deltas = [delta for delta in deltas if delta >= min_step]
        if len(real_deltas) >= 1:
            step = real_deltas[0]
            for index, padding in paddings.items():
                delta = padding - baseline
                if delta < min_step and index not in section_rows:
                    levels[index] = 0
                    continue
                if delta >= step and abs(delta / step - round(delta / step)) < 0.15:
                    levels[index] = max(levels.get(index, 0), round(delta / step))

    return levels


def _heal_grid(
    grid: list[list[str]],
    *,
    debug: bool = False,
    span_groups: list[SpanGroup] | None = None,
    table: object | None = None,
    header_count_override: int | None = None,
) -> tuple[list[list[str]], int]:
    """Analyze and repair column alignment and span groups across table rows."""
    if not grid:
        return [], 0
    width = max(map(len, grid))
    rows = [row + [""] * (width - len(row)) for row in grid]
    header_count, first_numeric_row = 0, len(rows)
    if header_count_override is not None:
        header_count = first_numeric_row = header_count_override
    for i, row in enumerate(rows):
        if header_count_override is not None:
            break
        values = [
            cell.strip()
            for cell in row
            if cell.strip()
            and cell.strip() not in PREFIX_SYMBOLS
            and cell.strip() not in SUFFIX_TOKENS
        ]
        numeric = sum(
            is_numeric_cell(cell) and not YEAR_TOKEN_RE.match(cell) for cell in values
        )
        if values and numeric / len(values) >= 0.25:
            header_count = first_numeric_row = i
            break

    if first_numeric_row == len(rows) and table is not None:
        header_count = _detect_explicit_header_count(table, len(rows))
        if not header_count:
            header_count = _detect_border_header_count(table, len(rows))
        if not header_count:
            header_count = _detect_header_like_first_row(table, len(rows))

    # Keep sparse section rows in the body after a multi-column header.
    for i in range(1, min(first_numeric_row, len(rows) - 1)):
        values = [cell.strip() for cell in rows[i] if cell.strip()]
        next_values = [cell.strip() for cell in rows[i + 1] if cell.strip()]
        previous_values = [cell.strip() for cell in rows[i - 1] if cell.strip()]
        if len(values) == 1 and UNITS_LABEL_RE.fullmatch(values[0]):
            header_count = i + 1
            break
        if len(values) <= 1 and len(next_values) <= 1 and len(previous_values) > 1:
            header_count = i
            break
        if (
            len(values) <= 1
            and len(previous_values) > 1
            and any(is_numeric_cell(value) for value in next_values)
        ):
            header_count = i
            break

    kept = apply_grid_repairs(rows, header_count, debug=debug, span_groups=span_groups)
    healed = [
        [
            NUMERIC_PERCENT_SPACE_RE.sub(
                r"\1%", PAREN_SPACES_RE.sub(r"(\1)", rows[r][c].strip())
            )
            for c in kept
        ]
        for r in range(len(rows))
    ]
    if debug:
        print(
            f"[table-debug] first_numeric_row={first_numeric_row} selected header_count={header_count}",
            file=sys.stderr,
        )
        for index, row in enumerate(healed):
            tag = "header" if index < header_count else "data"
            print(f"[table-debug] healed {tag} row {index}: {row!r}", file=sys.stderr)
    return healed, header_count


def convert_html_tables_to_ascii(
    html_content: str,
    *,
    debug: bool = False,
    section_context: SectionContext | None = None,
    table_context: TableContext | None = None,
    structure_index: HtmlStructureIndex | None = None,
) -> str:
    """Convert valid HTML financial tables into standardized ASCII tables.

    The optional context arguments are accepted as an extension of the
    public API (Phases E/F of the table-processing context refactor). When
    ``None`` (the default), behavior is identical to the standalone
    converter. When ``structure_index`` is passed, per-table context is
    resolved dynamically for each table in multi-table documents.
    """
    try:
        soup = BeautifulSoup(html_content, "lxml")
    except FeatureNotFound:  # pragma: no cover - parser availability varies
        soup = BeautifulSoup(html_content, "html.parser")
    for element in soup(
        ["head", "script", "style", "title", "meta", "noscript", "ix:hidden"]
    ):
        element.decompose()
    for element in soup.find_all(style=HIDDEN_ELEMENT_STYLE_RE):
        element.decompose()
    for comment in soup.find_all(string=lambda value: isinstance(value, Comment)):
        comment.extract()

    for table_index, table in enumerate(list(soup.find_all("table"))):
        rows = table.find_all("tr")
        if len(rows) <= 1:
            table.unwrap()
            continue

        ordinal = table_index + 1
        effective_section, effective_table = section_context, table_context
        if structure_index is not None:
            from defs.sec_forms.context import SectionContext, TableContext

            block = structure_index.block_for_table(ordinal)
            if block:
                effective_section = SectionContext(
                    document_id=structure_index.document_id,
                    source_sha256=structure_index.source_sha256,
                    heading=block.text,
                    preceding_blocks=block.preceding_blocks,
                    following_blocks=block.following_blocks,
                )
            effective_table = TableContext(
                section=effective_section,
                table_ordinal=ordinal,
                locator=f"table-{ordinal:06d}",
            )

        # 1. Early signature and bullet block templates
        signature_output = signature_template(table)
        if signature_output:
            table.replace_with(soup.new_string(signature_output))
            continue

        bullet_output = bullet_list_template(table)
        if bullet_output:
            table.replace_with(soup.new_string(bullet_output))
            continue

        # 2. Extract grid and test layout templates
        from .toc import looks_like_toc_text

        full_text = table.get_text(" ", strip=True).lower()
        scope = TableScope.from_string(
            "toc" if looks_like_toc_text(full_text) else "body"
        )
        cells = table.find_all(["td", "th"])
        non_empty = [cell_text(cell) for cell in cells if cell_text(cell)]
        numeric = sum(is_numeric_cell(cell) for cell in non_empty)
        source_grid, span_groups = span_grid(
            table,
            with_spans=True,
            join_fragmented_anchors=scope is TableScope.TOC,
        )

        template_result = apply_table_templates(
            table,
            source_grid,
            scope=scope,
            section_context=effective_section,
            table_context=effective_table,
        )
        if template_result is not None:
            table.replace_with(soup.new_string(template_result.text))
            continue

        # 3. Filter non-tabular blocks (< 15% numeric cells are unwrapped to text).
        if (
            len(rows) < 3
            or not non_empty
            or (scope is not TableScope.TOC and numeric / len(non_empty) < 0.15)
        ):
            fallback = row_aware_fallback(source_grid)
            if not fallback:
                fallback = oriented_prose_fallback(source_grid)
            if fallback:
                table.replace_with(soup.new_string(fallback))
            else:
                table.unwrap()
            continue

        if debug:
            print(
                f"[table-debug] table {table_index}: source grid "
                f"{len(source_grid)}x{max(map(len, source_grid), default=0)}",
                file=sys.stderr,
            )
            for index, row in enumerate(source_grid):
                print(f"[table-debug] source row {index}: {row!r}", file=sys.stderr)
            for row, start, end, label in span_groups:
                print(
                    f"[table-debug] span row {row}: columns {start}:{end} "
                    f"label={label!r}",
                    file=sys.stderr,
                )

        # 4. Standard financial table grid healing and ASCII rendering
        grid, header_count = _heal_grid(
            source_grid,
            debug=debug,
            span_groups=span_groups,
            table=table,
            header_count_override=(_toc_starts_with_part_heading(source_grid, scope)),
        )
        if not grid or len(grid[0]) <= 1:
            table.unwrap()
            continue
        converted = (
            HTMLTableConverter(
                grid=grid,
                header_row_count=header_count,
                section_levels=_detect_section_rows(table, grid, header_count),
                section_rows=_detect_section_row_indexes(table, grid, header_count),
                debug=debug,
            )
            .to_generic_table()
            .build()
        )
        if debug:
            print(
                f"[table-debug] table {table_index}: converted output", file=sys.stderr
            )
            print(converted, file=sys.stderr)
        table.replace_with(soup.new_string(converted))
    return soup.get_text(separator="\n")


__all__ = ["GenericTable", "HTMLTableConverter", "convert_html_tables_to_ascii"]
