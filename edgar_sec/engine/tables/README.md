# `edgar_sec/engine/tables` — protection, geometry, boundaries, rejection

## Purpose

Handles table rendering, row and boundary detection, false-grid rejection, table-family
classification, and protection of table text during prose rewrites.

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
| `toc/patterns.py` | Tabular TOC row patterns shared with cover detection. |
| `numeric_cells.py`, `tokens.py`, `currencies.py`, `units.py`, `patterns.py` | Financial-cell grammar, whitespace and dot-leader numeric-cell positions, attachment vocabulary, currency and measurement tables, and table pattern regexes. |

## Contracts

- **Table promotion is conservative.** Candidate rows require structural and numeric evidence;
  ambiguous regions are left unchanged.
- **Rendered geometry accompanies table text.** `TableGeometry` is retained through normalization.
- **Prose-rewriting passes mask tagged tables before changing text.**
- **Masking is idempotent-safe.** A document that already holds a sentinel is not re-masked, and a
  restore that cannot account for every span raises rather than returning text that silently lost a
  table.

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

## Command surface

None. Library package, no CLI.

## Mirrored tests

Mirrored coverage lives under `tests/engine/tables/`.

## Deliberate gaps

- **No geometry-driven review view.** Geometry is carried through normalization but is not
  rendered as a standalone review artifact.
- **Row-run detection is generic rather than form-specific.** Some financial
  tables are left unwrapped when their row geometry is ambiguous.
- **No per-column financial typing.** Currency and percentage semantics are not inferred.
- **No I/O, no network, no settings reads.** Enforced by the `layer-boundary` scanner: this package
  imports only `foundation`, `domain`, and sibling `engine` modules.
