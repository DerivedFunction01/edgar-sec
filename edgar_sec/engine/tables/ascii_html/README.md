# `engine.tables.ascii_html` — geometry-first HTML table rendering

## Purpose

Converts an HTML `<table>` into the canonical ASCII form (`<TABLE>` / aligned rows / dashed
dividers / `</TABLE>`) the rest of the normalization pipeline treats as the representation of a
financial statement.

The renderer works from estimated physical geometry rather than the DOM's row/column structure,
because a financial table is a grid of *columns* with right-aligned values, a header band separated
by a rule, and accounting micro-columns — a currency symbol, an amount, a footnote marker — that
belong to one value but arrive as three cells. A `TableGeometry` is retained per table so a
downstream consumer knows which rendered line is which logical row.

## Module → responsibility

| Module | Responsibility |
|---|---|
| `model.py` | Every public type: `CellStyle`, `SourceCell`, `SourceTable`, `CellBox`, `BorderSegment`, `SpanGroup`, `RenderBudget`, `ResolvedGrid`, `TableRenderResult`, `TableGeometry`, `TextLayoutDiagnostic`, `DEFAULT_RENDER_BUDGET`, and the alignment/border/vertical enums. |
| `cell.py` | Per-cell box (inline CSS + presentation attributes) and per-cell text (whitespace normalization, wrapping, padding, indent tiering). Formerly V1's `css.py` + `text.py`. |
| `widths.py` | `compute_column_widths`: column width allocation under `RenderBudget`, with layout diagnostics. |
| `balance.py` | Header segment sizing and sibling span width rebalancing, which moves width between columns rather than creating it. |
| `spans.py` | DOM extraction, `rowspan`/`colspan` ownership, nested table isolation, header band repair, multi-row span line distribution. |
| `columns.py` | Active column band resolution, alignment inference, spacer retention, affix column identification. |
| `borders.py` | Border segment extraction and the five-signal header boundary score. |
| `geometry.py` | `estimate_table_geometry`: logical cells to `CellBox` coordinates. |
| `blocks.py` | `RenderBlock` grouping and the affix/header fusion passes that keep a currency/amount/footnote triple in one right-aligned value. |
| `dividers.py` | Divider formatting plus three repairs: affix gap restoration, equal-length template healing, phantom fragment pruning. |
| `continuation.py` | Continuation detection across page breaks and the fusion of a repeated header. |
| `diagnostics.py` | `evaluate_table_confidence`: per-render confidence and the veto conditions that report a grid no longer describing the source table. |
| `quick_grid.py` | `quick_extract_table_grid`: text-only DOM scan that pre-filters layout tables without full CSS extraction. |
| `renderer.py` | `render_source_table` / `render_grid_to_ascii`: the staged pipeline, in order. |
| `converter.py` | The public entry points. |

## Contracts

- **One rendered line equals one logical row.** `TableGeometry.rows` is the resolved grid, never
  re-parsed from the emitted text. That is what makes the geometry metadata worth retaining.
- **Geometry is estimated, and says so.** A declared width or height scores `confidence` 1.0; a
  spanning cell 0.9; a cell inferred from content length at ~8px per character, 0.8.
- **A cell's text appears in exactly one column.** `build_span_matrix` resolves `rowspan`/`colspan`
  ownership once; every later stage reads positions.
- **Width is a budget, not a suggestion.** `RenderBudget` bounds the table, shrinking stops at each
  column's safe width, and only a dense multi-column numeric layout may take a bounded overflow.
- **Substitution is verified, not assumed.** The `__SEC_RENDERED_TABLE_{n}__` token path raises
  rather than returning a document with a table silently dropped.
- **Empty tables produce no output and no geometry.** A table with no visible text is decomposed.

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

`convert_html_table` accepts `str`, `bytes`, or a `FastHtmlNode` and returns a `TableRenderResult`.
`convert_html_tables_to_ascii_with_metadata` takes a whole document and returns
`(text, tuple[TableGeometry, ...])`, one geometry per table that produced output.

## Command surface

None. Library; the stage that drives it lives in `engine/document/html/normalizer.py`.

## Mirrored tests

`tests/engine/tables/ascii_html/` — `test_model.py`, `test_cell.py`, `test_spans.py`, `test_blocks.py`,
`test_borders.py`, `test_columns.py`, `test_continuation.py`, `test_diagnostics.py`,
`test_dividers.py`, `test_geometry.py`, `test_quick_grid.py`, `test_widths.py`, `test_balance.py`,
`test_renderer.py`, `test_converter.py` (234 tests).

## Deliberate gaps

### Omitted V1 symbols

| V1 symbol | V1 location | Reason omitted |
|---|---|---|
| `compute_column_widths` as a lazy module attribute | `ascii_html/text.py` (`__getattr__`) | A module-level forwarding shim to `widths.py`. V2 moved the function to its owning module and imports it from the leaf, so the shim has no consumer. |
| `split_wide_hyphenated` | `ascii_html/balance.py` | A byte-identical duplicate of the private `cell.py::_split_wide_hyphenated`, which is the live copy. Two implementations of one rule. |
| `_is_wholly_empty_table` | `ascii_html/__init__.py` | A private helper with zero callers. The live check is the converter's `_is_empty` closure, which memoizes per node because the document pass calls it up to three times per table. |

### Symbols that moved rather than disappeared

V1's `ascii_html/__init__.py` was a barrel re-exporting 24 symbols. V2 splits it: the three
conversion entry points stay in `converter.py`, the models move to `model.py`, and consumers import
from the leaf per `AGENTS.md` §1. Nothing was dropped — `TableGeometry`, `RenderBudget`,
`render_source_table`, `render_grid_to_ascii`, `extract_source_table`, `build_span_matrix`,
`detect_table_continuation`, `fuse_source_tables`, and `ContinuationDecision` are all still
reachable at their owning module.

V1's `css.py` became `cell.py` because the two halves of a cell — its box and its text — are both
per-cell operations no later stage revisits. `widths.py` and `balance.py` stay separate rather than
folding into `cell.py`: V1's four modules total 1,503 lines, which would breach the 800-line
`file-length` limit, while splitting any one of them would not.

### Known defects carried over from V1

Faithful ports of V1 behaviour, pinned by tests. Recorded here rather than fixed, because the
contract for this port is parity.

- **A bare `hidden` attribute never hides a cell.** The parser reports a valueless `hidden`
  attribute with a `None` value and the attribute map drops `None` values, so the
  `attrs.get("hidden") is not None` probe in `parse_style_and_attributes` cannot fire. Verified:
  `<td hidden>` yields `is_hidden=False`. Hiding requires `display:none` or `visibility:hidden` in
  the style attribute.
- **A cell with no attributes short-circuits to the shared default style.** An attribute-free `<td>`
  returns `_DEFAULT_CELL_STYLE` before the descendant scan, so a nested `<b>` or `<i>` in such a cell
  does not set `is_bold` / `is_italic`.
- **`is_affix_footnote_token` is a shape test, not a content test.** Any string of at most five
  characters that starts with `(` and ends with `)` counts as a footnote marker, including `()` and
  `(abc)`.
- **`is_numeric_cell` accepts any run of digits, commas, and periods.** The digit group is the
  character class `[\d,.]`, so `1.2.3` and `1,,2` are numeric cells. The predicate drives
  right-alignment, so this is a permissive edge rather than a data-loss path.
- **`is_false_table` expects rendered text, not raw HTML** — see `../false_tables/README.md`.