"""Generic text-based ASCII/SGML table layout builder and HTML grid converter."""

from __future__ import annotations

import sys
import warnings

from bs4 import BeautifulSoup, Comment, FeatureNotFound, XMLParsedAsHTMLWarning

# SEC filings are frequently served as XML (SGML/XHTML/XBRL) documents. The
# repository deliberately parses them with an HTML parser for table layout,
# so silence the bs4 warning rather than switching to an XML parser that
# would change the layout model.
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

from .builder import GenericTable, HTMLTableConverter
from .grid_repairs import SpanGroup, apply_grid_repairs
from .patterns import (
    HIDDEN_ELEMENT_STYLE_RE,
    NUMERIC_PERCENT_SPACE_RE,
    PAREN_SPACES_RE,
    YEAR_TOKEN_RE,
)
from .templates import (
    TableScope,
    apply_table_templates,
    bullet_list_template,
    cell_text,
    signature_template,
    span_grid,
)
from .tokens import is_numeric_cell


def _heal_grid(
    grid: list[list[str]],
    *,
    debug: bool = False,
    span_groups: list[SpanGroup] | None = None,
) -> tuple[list[list[str]], int]:
    """Analyze and repair column alignment and span groups across table rows."""
    if not grid:
        return [], 0
    width = max(map(len, grid))
    rows = [row + [""] * (width - len(row)) for row in grid]
    header_count, first_numeric_row = 1, len(rows)
    for i, row in enumerate(rows):
        values = [cell.strip() for cell in row if cell.strip()]
        numeric = sum(
            is_numeric_cell(cell) and not YEAR_TOKEN_RE.match(cell) for cell in values
        )
        if values and numeric / len(values) >= 0.25:
            header_count = first_numeric_row = i
            break

    # Keep sparse section rows in the body after a multi-column header.
    for i in range(1, min(first_numeric_row, len(rows) - 1)):
        values = [cell.strip() for cell in rows[i] if cell.strip()]
        next_values = [cell.strip() for cell in rows[i + 1] if cell.strip()]
        previous_values = [cell.strip() for cell in rows[i - 1] if cell.strip()]
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
            f"[table-debug] first_numeric_row={first_numeric_row} "
            f"selected header_count={header_count}",
            file=sys.stderr,
        )
        for index, row in enumerate(healed):
            print(
                f"[table-debug] healed "
                f"{'header' if index < header_count else 'data'} row {index}: {row!r}",
                file=sys.stderr,
            )
    return healed, header_count


def convert_html_tables_to_ascii(html_content: str, *, debug: bool = False) -> str:
    """Convert valid HTML financial tables into standardized ASCII tables."""
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
        full_text = table.get_text(" ", strip=True).lower()
        scope = TableScope.from_string(
            "toc"
            if ("item" in full_text and "page" in full_text and "part i" in full_text)
            else "body"
        )
        cells = table.find_all(["td", "th"])
        non_empty = [cell_text(cell) for cell in cells if cell_text(cell)]
        numeric = sum(is_numeric_cell(cell) for cell in non_empty)
        source_grid, span_groups = span_grid(table, with_spans=True)

        template_result = apply_table_templates(table, source_grid, scope=scope)
        if template_result is not None:
            table.replace_with(soup.new_string(template_result.text))
            continue

        # 3. Filter non-tabular blocks.
        #    The numeric-density guard is intentional: tables used purely for
        #    prose layout (< 15% numeric cells) are unwrapped to plain text.
        #    Templates that match non-numeric cover grids or checkbox tables set
        #    bypass_guard=True on their TemplateResult so they are consumed above
        #    before ever reaching this check — no special handling needed here.
        if (
            len(rows) < 3
            or not non_empty
            or (scope is not TableScope.TOC and numeric / len(non_empty) < 0.15)
        ):
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
            source_grid, debug=debug, span_groups=span_groups
        )
        if not grid or len(grid[0]) <= 1:
            table.unwrap()
            continue
        converted = (
            HTMLTableConverter(grid=grid, header_row_count=header_count)
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
