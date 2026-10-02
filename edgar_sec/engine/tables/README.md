# `edgar_sec/engine/tables` — protection, geometry, boundaries, rejection

## Purpose

Everything the engine does to a filing table. The package is split on one seam — *who is allowed
to rewrite a table*:

- **`protection/`** guarantees tagged table bytes survive every prose pass untouched.
- **`ascii_html/`** renders an HTML `<table>` into canonical ASCII plus a `TableGeometry`.
- **`false_tables/`** decides when an aligned grid was never a table and unwraps it.
- **`resolver.py` + `structural.py` + `policy/`** decide where an *untagged* table begins and stops.
- **`hybrid/`** protects `<pre>` payloads a DOM cannot represent faithfully.
- **`taxonomy/`** scores a grid against registered table families.
- **the leaf modules** (`numeric_cells`, `tokens`, `currencies`, `units`, `patterns`) hold the shared
  financial-cell and pattern vocabulary everything above depends on.

## Layout

| Module | Responsibility |
| :--- | :--- |
| `protection/tags.py` | Byte-exact `<TABLE>` span masking and restoration. See `protection/README.md`. |
| `ascii_html/{model,cell,spans,columns,borders,geometry,blocks,dividers,continuation,diagnostics,quick_grid,widths,balance,renderer,converter}.py` | Geometry-first HTML→ASCII conversion. See `ascii_html/README.md`. |
| `false_tables/{detector,unwrapper}.py` | Layout-grid rejection and prose unwrapping. See `false_tables/README.md`. |
| `hybrid/masker.py` | `<pre>` payload masking. See `hybrid/README.md`. |
| `resolver.py` | `resolve_table_regions`: grow confirmed table decisions outward, absorbing prefix, bridge, tail, and continuation. |
| `row_runs.py` | Generic cell geometry and repeated numeric row-run detection within packed blocks or across one blank line; no filing-family vocabulary. |
| `structural.py` | `is_header_prefix`, `is_structural_table_bridge`, `is_structural_table_tail` — regex answers about a candidate span's own lines. |
| `policy/{intro,continuation}.py` | `split_structural_table_intro`, `is_tableish_block`, `unify_table_prose`, `is_table_row_continuation`. See `policy/README.md`. |
| `taxonomy/{classifier,context,shapes}.py` | Multi-zone family classification. See `taxonomy/README.md`. |
| `toc/patterns.py` | Tabular TOC row patterns shared with cover TOC detection; the leaf that broke V1's lazy `sec_forms.cover` import. |
| `numeric_cells.py`, `tokens.py`, `currencies.py`, `units.py`, `patterns.py` | Financial-cell grammar, whitespace and dot-leader numeric-cell positions, attachment vocabulary, currency and measurement tables, and table pattern regexes. |

## Contracts

- **Tagging a table is opt-in and the default answer is refuse.** `row_runs.py` can promote a
  bounded run of at least three numeric multi-cell rows when numeric-cell anchors repeat. Rows may
  vary in label-field count or include aligned nonnumeric continuations; the shared reflow cascade
  assesses the combined run for numeric-table and linguistic-prose evidence. Packed rows and
  one-blank gaps are recognized; confirmed runs may join across short separator, year-label, or
  numeric subtotal bridges. The resolver separately grows existing decisions only on explicit
  header, bridge, tail, or continuation evidence. A confirmed run can absorb a contained table
  decision and extend a partially overlapping one; a table decision that already contains the run
  is left unchanged.
- **Rendering is geometry-first and honest about it.** A converted table yields a `TableGeometry`
  whose `rows` are the resolved grid, never re-parsed from emitted text, and every `CellBox`
  records how its bounds were derived (declared width, span, or content length). See
  `ascii_html/README.md`.
- **Every prose-rewriting stage must mask before it rewrites.** HTML cleaning, break injection, cover
  healing, checkmark rewriting, whitespace normalization, and reflow all mask through
  `protection/tags.py`; that is the enforcement mechanism, not a convention. One sentinel protocol,
  one leaf.
- **Masking is idempotent-safe.** A document that already holds a sentinel is not re-masked, and a
  restore that cannot account for every span raises rather than returning a document that quietly
  lost a table. Masked offsets are *not* source offsets.
- **Geometry metadata is produced, serialized, and read back.** `TableGeometry` instances flow into
  `NormalizationResult.table_geometries`, are serialized by
  `pipelines/document_storage/review_artifacts.py`, and are translated across cover checkmark
  rewriting by `update_table_geometries`.

## Public surface

No re-exports: every consumer imports the leaf module it needs.

```python
from edgar_sec.engine.tables.ascii_html.converter import (
    convert_html_tables_to_ascii_with_metadata,
)
from edgar_sec.engine.tables.protection.tags import (
    mask_tagged_tables,
    restore_tagged_tables,
)
from edgar_sec.engine.tables.resolver import resolve_table_regions
from edgar_sec.engine.tables.row_runs import find_table_row_runs
```

Callers that do not import this package directly: `engine/document/html/normalizer.py` (the
conversion stage), `engine/forms/normalize.py` (`normalize_document`), and
`engine/reflow/engine/rewrapper.py` (mask/restore, tag boundaries, the resolver).

## Command surface

None. Every module is library code; `engine/forms/normalize.py` is the composition seam.

## Mirrored tests

`tests/engine/tables/` — mirrored tests cover rendering, protection, row-run geometry, and boundaries:

| Directory | Tests |
| :--- | ---: |
| `tests/engine/tables/ascii_html/` | 234 |
| `tests/engine/tables/false_tables/` | 57 |
| `tests/engine/tables/policy/` | 37 |
| `tests/engine/tables/protection/` | 26 |
| `tests/engine/tables/taxonomy/` | 24 |
| `tests/engine/tables/hybrid/` | 20 |
| `tests/engine/tables/toc/` | 10 |
| `tests/engine/tables/` (leaf modules including `test_row_runs.py`, `test_resolver.py`, `test_structural.py`, and shared vocabulary tests) | see mirrored files |

## Deliberate gaps

- **No geometry-driven consumer yet.** `TableGeometry` is produced and serialized but nothing
  renders a review artifact *from* it; `edgar_sec/engine/document/page_markers/` does its own
  repeating-header analysis.
- **No page-furniture detection inside tables.** Rendered table furniture is admitted through
  `allow_table_furniture` in the page-marker detector; `engine/tables/` contributes no header-row
  template of its own.
- **`is_false_table` requires *rendered* text, not raw HTML.** Without geometry it strips only the
  `<TABLE>` wrapper, so a body still carrying `<TR>`/`<TD>` never matches the leading-heading
  patterns and is classified as a false table. Callers pass rendered text; geometry is preferred.
- **A bare `hidden` attribute does not hide a cell.** Carried over from V1 and pinned by test. See
  `ascii_html/README.md` § Known defects.
- **Row-run detection is deliberately generic, not complete.** It does not infer semantic headers,
  recognize issuer or filing-specific row grammars, or bridge large gaps. Short tables below the
  three-row minimum and nonnumeric tables are not promoted. Repeated numeric columns may include
  a plain label/page-number layout when its row geometry is compatible; alphabetic-only headers can
  remain outside the wrapper, and runs before the reflow body's detected start are not considered.
  Ambiguous sentence-like candidates are preserved rather than forced into a wrapper.
- **No per-column financial typing.** A column is right-aligned because its cells match
  `is_numeric_cell`, not because the taxonomy decided it is a currency or a percentage. That
  judgement lives in `taxonomy/`, which has no production consumer.
- **No public API for the leaf vocabulary.** `tokens.py` re-exports four predicates from
  `numeric_cells.py` because both the renderers and the reflow feature extractor need the same
  grammar; that overlap is deliberate, not a shim.
- **No I/O, no network, no settings reads.** Enforced by the `layer-boundary` scanner: this package
  imports only `foundation`, `domain`, and sibling `engine` modules.
