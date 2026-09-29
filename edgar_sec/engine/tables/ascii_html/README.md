# `edgar_sec/engine/tables/ascii_html` — geometry-first HTML table to canonical ASCII renderer

Reconstructs a visual HTML table as a monospaced grid: reads cell styles and spans, estimates
physical column geometry, budgets widths, and emits a `<TABLE>`-delimited ASCII block that
preserves the original column alignment. It is the only part of the engine that reconstructs
*visual* layout from CSS.

Sixteen modules: fifteen stages plus `__init__.py`. `model.py` is the data model everything else
speaks in; `renderer.py` is the driver; the remaining thirteen are single-responsibility stages.

## Purpose

A 2020s 10-K HTML table is a presentation artifact. Its numbers are aligned by CSS
`text-align: right` and by `width` attributes, not by whitespace. `decompose_html_structures`
would flatten it into an unreadable run of values, so `ascii_html` intercepts it *before* that
and reconstructs the column grid the filer intended.

The output is the same `<TABLE>...</TABLE>` token the rest of `edgar_sec/engine/tables/`
protects byte-for-byte. `renderer.py` emits `lines[0] == "<TABLE>"` and
lines[-1] == "</TABLE>"` (`renderer.py:233`, `:448`), so a rendered table is indistinguishable
from a legacy tagged table to every downstream consumer.

## Layout

| Module | Responsibility |
| :--- | :--- |
| `model.py` | The core data model. Frozen dataclasses `SourceCell`, `SourceTable`, `CellBox`, `BorderSegment`, `CellStyle`, `SpanGroup`, `ResolvedGrid`, `TableRenderResult`, `TableGeometry`, `RenderBudget`, `TextLayoutDiagnostic`; the `HorizontalAlign` / `VerticalAlign` / `BorderStyle` enums; `DEFAULT_RENDER_BUDGET`. |
| `renderer.py` | The driver. `render_source_table` runs the nine-step pipeline below; `render_grid_to_ascii` renders a bare 2D text matrix with no HTML at all. |
| `spans.py` | DOM extraction and span tracking. `extract_source_table` walks only rows and cells belonging directly to a table (nested tables become separate `SourceTable` values referenced by index), `build_span_matrix` materialises the colspan/rowspan grid, `repair_header_band_spans`, `distribute_multi_row_span_lines`. |
| `css.py` | Unit-aware CSS and HTML attribute parsing. `parse_style_and_attributes` builds a `CellStyle` from a `style` attribute plus presentation attributes; `parse_dimension_px` converts lengths. `lru_cache`d. |
| `geometry.py` | `estimate_table_geometry` — coordinate estimation, producing a `CellBox` per cell with a confidence. |
| `columns.py` | Column band inference. `resolve_columns` picks the active columns, their alignments, and the spacer columns; `identify_affix_columns` finds currency-prefix/suffix columns; `is_structural_spacer` classifies a zero-content gutter. |
| `borders.py` | `extract_border_segments` turns cell border styles into discrete per-edge `BorderSegment`s; `score_header_boundary` uses them plus other signals to decide where the header ends. |
| `blocks.py` | The render block model. `RenderBlock`, `build_row_blocks`, and the four fusions: `fuse_header_suffix_blocks`, `fuse_data_affix_blocks`, `fuse_empty_header_span_blocks`, `expand_numeric_blocks_to_header_bands`, plus `align_terminal_numeric_headers` and `extract_raw_grids_and_spans`. |
| `widths.py` | `compute_column_widths` — optimal width allocation under the `RenderBudget`, emitting a `TextLayoutDiagnostic` for every forced wrap or clip. |
| `balance.py` | Sibling span width balancing: `balance_span_widths`, `balanced_wrap_width`, `header_minimum_width`, `preferred_header_width`, `split_wide_hyphenated`. |
| `text.py` | Cell text layout: `wrap_cell_text`, `format_cell_line`, `normalize_grid_indents`. |
| `dividers.py` | Horizontal rule formatting and repair: `format_top_divider`, `format_row_divider`, `heal_divider_lines_from_templates`, `prune_unanchored_divider_fragments`, `repair_rendered_affix_columns`. |
| `diagnostics.py` | `evaluate_table_confidence` — returns a confidence in `[0, 1]` plus a list of veto reasons (empty table, multi-cell table collapsed to one column, cells clipped by the budget, excessive span complexity). |
| `continuation.py` | Domain-neutral continuation detection and pre-render fusion: `ContinuationDecision`, `detect_table_continuation`, `fuse_source_tables`, `is_allowed_intervening_content`. A statement split across a page break becomes one table again. |
| `quick_grid.py` | `quick_extract_table_grid` — a text-only DOM scan used to pre-filter false tables *without* CSS parsing. Returns `None` (bail to full extraction) when the table uses colspan/rowspan or contains a nested `<table>`. |
| `__init__.py` | The document-level entry points: `convert_html_table` (one table), `convert_html_tables_to_ascii` and `convert_html_tables_to_ascii_with_metadata` (a whole document), which find top-level tables, pre-filter false ones, cluster continuations, render each cluster, and splice the ASCII back into the tree. |

## The render pipeline

`render_source_table` (`renderer.py:82-455`) is a fixed nine-step order. The order is
load-bearing: each step consumes the previous step's output and narrows the coordinate space.

1. **Extract** — `extract_source_table` produces a `SourceTable` with nested tables isolated
   (`renderer.py:89-92`).
2. **Span matrix and geometry** — `build_span_matrix` plus `repair_header_band_spans`, then
   strip leading and trailing all-empty spacer rows, then `estimate_table_geometry`
   (`renderer.py:97-112`).
3. **Columns** — `resolve_columns` yields active columns, alignments, and spacers; if no column
   survives, all columns are active and `LEFT`. `identify_affix_columns` then locates
   currency-symbol columns (`renderer.py:115-122`).
4. **Borders and header boundary** — `extract_border_segments` then `score_header_boundary`
   (`renderer.py:125-128`).
5. **Text grid** — `extract_raw_grids_and_spans` produces the 2D text grid plus span
   constraints; `normalize_grid_indents` strips discrete indentation. A single reverse pass
   classifies every row as `(is_empty, has_numeric)` and marks *terminal header rows* — text-only
   rows sitting directly above the first numeric data row (`renderer.py:141-165`).
6. **Widths** — `compute_column_widths` under the budget, producing `TextLayoutDiagnostic`s
   (`renderer.py:168-175`).
7. **Confidence** — the `ResolvedGrid` is assembled and `evaluate_table_confidence` returns
   `(confidence, veto_reasons)` (`renderer.py:178-191`).
8. **Border index** — segments are flattened into per-row top/bottom style maps, with `DOUBLE`
   winning over any other style (`renderer.py:194-206`).
9. **Format** — `build_row_blocks` per row, then the fusion pipeline
   (`fuse_header_suffix_blocks` → `fuse_data_affix_blocks` →
   `expand_numeric_blocks_to_header_bands` → `fuse_empty_header_span_blocks` →
   `align_terminal_numeric_headers`), then `wrap_cell_text`, then
   `distribute_multi_row_span_lines`, then per-row line emission honouring `vertical_align`,
   then `format_row_divider`/`format_top_divider`, then the three repair passes
   (`repair_rendered_affix_columns`, `heal_divider_lines_from_templates`,
   `prune_unanchored_divider_fragments`), then a common leading-space trim, then `</TABLE>`
   (`renderer.py:208-448`).

At the document level, `convert_html_tables_to_ascii_with_metadata` (`__init__.py:97-335`) adds
three stages around that: **pre-filter** (`quick_extract_table_grid` → `is_false_grid` →
`unwrap_grid`, with a footnote-context lookahead for a table immediately preceding a retained
one), **cluster** (adjacent tables with equal column counts and ≤100 intervening characters of
non-table text are fused via `detect_table_continuation` / `fuse_source_tables`), and
**splice** (the rendered ASCII replaces the table node, either directly or via a
`__SEC_RENDERED_TABLE_{n}__` token when `convert_to_text=False`; a missing token at splice time
raises `ValueError`).

## Contracts

- **Output is always `<TABLE>`-delimited.** `render_source_table` returns `ascii_text` starting
  with `<TABLE>` and ending with `</TABLE>`, so `mask_tagged_tables` protects rendered tables
  with no special case.
- **One rendered table is not one rendered line.** Wrapped cells span multiple lines; the row
  count is *not* recoverable from the text. `TableGeometry.rows` exists for that reason and its
  docstring is explicit: "Logical grid rows; never inferred from rendered text lines"
  (`model.py:244-245`).
- **Geometry is retained, not reconstructed by the caller.**
  `convert_html_tables_to_ascii_with_metadata` returns `tuple[TableGeometry, ...]`, one per
  table that produced output. Wholly-empty tables that are decomposed are omitted, matching the
  string output (`__init__.py:105-109`).
- **Confidence is reported, never acted on.** `evaluate_table_confidence` returns a float and a
  list of veto reasons; `render_source_table` attaches both to `TableRenderResult` and does not
  suppress output on a low score. A caller that wants a veto to reject the table must read
  `veto_reasons` itself.
- **Every budget knob is a `RenderBudget` field**, not a literal: `max_table_width=180`,
  `max_column_width=48`, `max_text_column_width=80`, `minimum_numeric_width=8`,
  `column_spacing=2`, `max_dense_table_overflow=48`, `dense_table_min_columns=10`
  (`model.py:147-157`). A caller that needs a different ceiling passes a replacement budget;
  the `resource-allocation` scanner keeps thread and memory literals out of the package.
- **Hidden content is dropped at extraction.** `extract_source_table` skips rows and cells whose
  parsed style sets `is_hidden` (`spans.py:76-78`, `:91`), and `HIDDEN_ELEMENT_STYLE_RE`
  (`display:none` / `visibility:hidden`) is the detector.
- **Layer discipline.** The sub-package imports `engine.document` (`FastHtmlNode`,
  `parse_html`), sibling `engine.tables` (`numeric_cells`, `patterns`, `protection`,
  `false_tables` lazily), and `foundation`. It imports nothing upward.
- **No entry point.** There is no `python -m edgar_sec.engine.tables.ascii_html` invocation; the
  three `convert_*` functions are ordinary library calls. The only production caller of the
  rendered output is `edgar_sec/engine/forms/normalize.py`, reached through the composition
  seam, and `false_tables` is imported lazily inside
  `convert_html_tables_to_ascii_with_metadata` (`__init__.py:148`).

## Public surface

Consumers should import from the leaf module or, for the three document-level functions, from
the package `__init__`.

- `convert_html_table` — convert one `<table>` given as `str`, `bytes`, or `FastHtmlNode`.
  `edgar_sec/engine/tables/ascii_html/__init__.py:51`.
- `convert_html_tables_to_ascii` — convert every table in a document to text.
  `edgar_sec/engine/tables/ascii_html/__init__.py:82`.
- `convert_html_tables_to_ascii_with_metadata` — same, plus the per-table `TableGeometry` tuple.
  `edgar_sec/engine/tables/ascii_html/__init__.py:97`.
- `render_source_table` — render one `SourceTable` or `FastHtmlNode`; the nine-step pipeline.
  `edgar_sec/engine/tables/ascii_html/renderer.py:82`.
- `render_grid_to_ascii` — render a bare `list[list[str]]` grid with derived alignments.
  `edgar_sec/engine/tables/ascii_html/renderer.py:458`.
- `extract_source_table` — DOM → `SourceTable` plus isolated nested tables.
  `edgar_sec/engine/tables/ascii_html/spans.py:48`.
- `build_span_matrix` — `SourceTable` → 2D `SourceCell | None` matrix plus `SpanGroup`s.
  `edgar_sec/engine/tables/ascii_html/spans.py`.
- `parse_style_and_attributes` — `style` attribute + presentation attributes → `CellStyle`.
  `edgar_sec/engine/tables/ascii_html/css.py`.
- `estimate_table_geometry` — `SourceTable` + span matrix → per-cell `CellBox`.
  `edgar_sec/engine/tables/ascii_html/geometry.py`.
- `resolve_columns` / `identify_affix_columns` / `is_structural_spacer` — column band
  inference. `edgar_sec/engine/tables/ascii_html/columns.py`.
- `extract_border_segments` / `score_header_boundary` — border extraction and header scoring.
  `edgar_sec/engine/tables/ascii_html/borders.py`.
- `build_row_blocks` and the five fusion functions — the block model.
  `edgar_sec/engine/tables/ascii_html/blocks.py`.
- `compute_column_widths` — width allocation under the budget; returns
  `(widths, diagnostics)`. `edgar_sec/engine/tables/ascii_html/widths.py`.
- `balance_span_widths` / `balanced_wrap_width` / `header_minimum_width` /
  `preferred_header_width` / `split_wide_hyphenated` — sibling span sizing.
  `edgar_sec/engine/tables/ascii_html/balance.py`.
- `wrap_cell_text` / `format_cell_line` / `normalize_grid_indents` — cell text layout.
  `edgar_sec/engine/tables/ascii_html/text.py`.
- `format_top_divider` / `format_row_divider` / `heal_divider_lines_from_templates` /
  `prune_unanchored_divider_fragments` / `repair_rendered_affix_columns` — rule formatting and
  repair. `edgar_sec/engine/tables/ascii_html/dividers.py`.
- `evaluate_table_confidence` — `(confidence, veto_reasons)`.
  `edgar_sec/engine/tables/ascii_html/diagnostics.py:15`.
- `detect_table_continuation` / `fuse_source_tables` / `is_allowed_intervening_content` /
  `ContinuationDecision` — pre-render fusion of a statement split across a page break.
  `edgar_sec/engine/tables/ascii_html/continuation.py`.
- `quick_extract_table_grid` — the no-CSS pre-filter scan; returns `None` to bail.
  `edgar_sec/engine/tables/ascii_html/quick_grid.py:24`.
- `RenderBudget` / `DEFAULT_RENDER_BUDGET` — the width budget.
  `edgar_sec/engine/tables/ascii_html/model.py:147` and `:159`.
- `TableGeometry` / `TableRenderResult` / `ResolvedGrid` / `SourceTable` / `SourceCell` /
  `CellStyle` / `CellBox` / `BorderSegment` / `SpanGroup` / `TextLayoutDiagnostic` — the model.
  `edgar_sec/engine/tables/ascii_html/model.py`.

## Tests

`tests/engine/tables/ascii_html/test_renderer.py` renders a real financial table
through the public `SourceTable` seam and asserts the output, the grid shape,
column alignment, a range marker surviving the render, confidence bounds, and the
empty-table case. It exists because the package was dead for its whole lifetime
with 1,248 green tests, and an import smoke test alone would have proven it
loadable rather than load-bearing.

The restored token predicates are pinned at their own mirrored home:
`tests/engine/tables/test_numeric_cells.py` covers `CLOSING_DELIMITERS`,
`RANGE_MARKERS`, `is_range_marker`, `is_suffix_token`, and the invariant that
`SUFFIX_TOKENS` is built from the named closing delimiters.

`tests/test_package_imports.py` imports every package in the repository, so a
package that stops importing fails the gate instead of sitting unnoticed.

This still violates `AGENTS.md` §6 ("one test file per source module") for
**fifteen** of the sixteen modules: only `renderer.py` has a mirrored test file.
An earlier revision of this section claimed the HTML entry points were untested
because `selectolax` was not installed — that was wrong: the package is installed
in the venv, and the check had been run with the system `python3` instead of
`.venv/bin/python`.

## Deliberate gaps

- **The package did not import until 2026-09-29, because v1's `defs/tables/tokens.py`
  was never ported.** That file was a facade: it re-exported everything the package
  needed from `currencies`, `numeric_cells`, `dates`, `tokens` and `patterns`, and
  also defined four things that existed nowhere else — `CLOSING_DELIMITERS`,
  `RANGE_MARKERS` with `is_range_marker`, and `is_suffix_token`. The v2 split moved
  the facade's re-exports to their real owners but dropped its four definitions, so
  five sub-modules imported names that did not exist. Fixed by porting the four into
  `engine/tables/numeric_cells.py` beside their siblings (`is_prefix_token`,
  `SUFFIX_TOKENS`, `numeric_cell_starts`), re-pointing `is_year_token` to
  `foundation/text/dates.py` and `ALL_CURRENCY_SYMBOLS` to `engine/tables/currencies.py`,
  and renaming `PREFIX_SYMBOLS` to v2's `PREFIX_TOKENS` — which is the same set with
  the open paren folded in. `dividers.py` subtracts `{"(", "-"}` from it, so the
  rename is behaviour-preserving there.
- **`__init__.py` re-exported 21 child symbols until 2026-09-29.** It listed all 24
  package symbols in `__all__`, of which only three — `convert_html_table`,
  `convert_html_tables_to_ascii`, `convert_html_tables_to_ascii_with_metadata` — are
  defined in the module itself. `AGENTS.md` §1.2 forbids re-exporting child symbols from
  an `__init__.py`, and the effect was more than cosmetic: the package looked like a single
  opaque surface, which is what let five sub-modules import nonexistent names without any
  test noticing. `__all__` now carries only the three converters, and consumers import the
  model dataclasses and the render/extract/span helpers from their own modules.
- **`TableGeometry` is not produced on the common path.** Only
  `convert_html_tables_to_ascii_with_metadata` returns it. `convert_html_table` and
  `render_source_table` return a `TableRenderResult` that the caller must wrap by hand
  (`__init__.py:290-295` shows the wrapping). A caller reading
  `edgar_sec/engine/document/html.py::NormalizedHtmlText.table_geometries` gets `()` — see
  `edgar_sec/engine/document/README.md`.
- **No caption handling.** `CAPTION_RE` exists in
  `edgar_sec/engine/tables/patterns.py` but has no importer; nothing in this package reads a
  `<caption>`, and a caption that is not itself a `<td>` is not rendered.
- **No `<S>`/`<C>` marker rendering.** `S_MARKER_RE` and `C_MARKER_RE` are declared in
  `tables/patterns.py` and unconsumed. The renderer produces aligned whitespace, not SGML cell
  markers.
- **No fusion across a document boundary, and no order guarantee on the fused grid.**
  `continuation.py` fuses *adjacent* tables in one document when the intervening text is ≤100
  non-table characters (`__init__.py:239`); it will not fuse a table with one in a different
  filing. The fused result is `fuse_source_tables(prev_source, source, decision.header_rows_to_drop)`,
  so the continuation's repeated header is dropped only as far as the continuation decision
  says (`__init__.py:255-257`) — a false `is_continuation` verdict loses a header row silently,
  because nothing downstream re-checks it.
- **v1's `defs/tables/detector.py` (380 lines) and `grid.py` (260 lines) were reconciled rather
  than ported.** Roadmap `roadmap/refactor_v2/phase_2_5/04_engine_tables_and_forms.md` M4.1
  records: "Shipped in sub-plan 02 under different names than planned; reconciled rather than
  rebuilt." The `detector.py` / `grid.py` module names in the roadmap's §2 inventory table do
  not exist in v2; the responsibilities live across `ascii_html/` and `resolver.py`.
- **Confidence scoring is shallow.** `diagnostics.py` is 62 lines and applies four checks
  (empty table, single-column collapse, clipping, span complexity). There is no learned model,
  no golden-corpus calibration, and no `check.py --goldens` harness to back the numbers.
