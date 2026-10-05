# `engine.tables.ascii_html` — geometry-first HTML table rendering

## Purpose

Converts HTML tables to the canonical ASCII table representation and returns
row geometry for downstream consumers.

## Module → responsibility

| Module | Responsibility |
|---|---|
| `model.py` | Shared renderer types and defaults. |
| `cell.py` | Cell text and style handling. |
| `widths.py`, `balance.py` | Column sizing and span-width balancing. |
| `spans.py`, `columns.py`, `borders.py`, `geometry.py` | Table structure and geometry. |
| `blocks.py`, `dividers.py`, `continuation.py` | Rendered rows, dividers, and page continuation. |
| `diagnostics.py`, `quick_grid.py` | Confidence assessment and lightweight grid extraction. |
| `renderer.py`, `converter.py` | Rendering and document-level conversion APIs. |

## Contracts

- **One rendered line equals one logical row.** `TableGeometry.rows` is the resolved grid, never
  re-parsed from the emitted text. That is what makes the geometry metadata worth retaining.
- **Geometry is estimated.** The result carries confidence information for
  inferred dimensions.
- **A cell's text appears in exactly one column.** `build_span_matrix` resolves `rowspan`/`colspan`
  ownership once; every later stage reads positions.
- **Rendered width respects the supplied budget.**
- **A failed table substitution is reported, not silently omitted.**
- **Empty tables produce no output or geometry.**

## Public surface

Import from the leaf module; `__init__.py` is a docstring and re-exports nothing.

```python
from edgar_sec.engine.tables.ascii_html.converter import (
    convert_html_table,
    convert_html_tables_to_ascii,
    convert_html_tables_to_ascii_with_metadata,
)
from edgar_sec.engine.tables.ascii_html.model import RenderBudget, TableGeometry
from edgar_sec.engine.tables.ascii_html.renderer import (
    render_grid_to_ascii,
    render_source_table,
)
```

## Command surface

None. Library package, no CLI.

## Mirrored tests

Mirrored coverage lives under `tests/engine/tables/ascii_html/`.

## Deliberate gaps

### Known defects

- **A bare `hidden` attribute never hides a cell.** The parser reports a valueless `hidden`
  attribute with a `None` value and the attribute map drops `None` values, so the
  `attrs.get("hidden") is not None` probe in `parse_style_and_attributes` cannot fire. Verified:
  `<td hidden>` yields `is_hidden=False`. Hiding requires `display:none` or `visibility:hidden` in
  the style attribute.
- **Descendant text styling is not detected when a cell has no attributes.**
- **Footnote and numeric-cell checks are permissive shape checks, not full parsers.**
- **`is_false_table` expects rendered text, not raw HTML** — see `../false_tables/README.md`.
