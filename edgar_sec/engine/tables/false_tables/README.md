# `engine.tables.false_tables` — layout-grid rejection and prose unwrapping

## Purpose

A filing uses HTML tables for things that are not tables: a single bulleted risk-factor row, an
exhibit index, a two-column heading, a footnote block. Rendering those as aligned ASCII destroys
them; leaving them as grids produces noise.

This package answers "is this really a table?" from the *resolved grid* rather than from the rendered
text, because a layout grid's shape — one marker column beside one prose column — is the evidence,
and rendered wrapping has already destroyed it. When the answer is no, it rebuilds readable text.

## Module → responsibility

| Module | Responsibility |
|---|---|
| `detector.py` | `is_false_grid` (judges a resolved grid) and `is_false_table` (judges a rendered `<TABLE>` block, or a rendered block plus its geometry), plus the private marker, prose, and ordered-outline predicates. |
| `unwrapper.py` | `unwrap_grid` (rebuild prose or a list from a rejected grid) and `cleanup_false_tables_with_metadata` (rewrite the surrounding text while keeping the surviving geometry aligned with the surviving text). |

## Contracts

- **A retained table is never rewritten.** The rewrite only removes blocks the detector rejected;
  a retained block is re-emitted as `match.group(0)`. The returned text is `strip()`ped, so
  leading and trailing whitespace of the whole document is not preserved.
- **A rejected grid becomes readable text.** An ordered or bulleted grid becomes one item per line;
  a prose grid becomes joined prose. Consecutive unwrapped blocks join the way the surrounding prose
  would have joined them: a newline between list items so they stay a list, a space between prose
  fragments so they stay a sentence.
- **Geometry follows the text.** Every block the rewrite removes is dropped from the returned
  geometry tuple too, so metadata and text stay in correspondence.
- **The refusal is conservative.** A grid is retained when its second column carries a numeric
  value, when its first column is an `ITEM`/`PART` reference or a TOC row, or when the rendered text
  is a bare numeric separator.

## Public surface

```python
from edgar_sec.engine.tables.false_tables.detector import (
    is_false_grid,
    is_false_table,
)
from edgar_sec.engine.tables.false_tables.unwrapper import (
    cleanup_false_tables_with_metadata,
    unwrap_grid,
)
```

`cleanup_false_tables_with_metadata(text, geometries)` returns `(text, tuple[TableGeometry, ...])`.
A footnote-shaped table immediately preceding a retained table unwraps too, but only when it passes
`is_false_table(..., allow_footnote_context=True)` on its geometry.

## Command surface

None. Library; the stage that drives it lives in `engine/document/html/normalizer.py`.

## Mirrored tests

`tests/engine/tables/false_tables/` — `test_detector.py`, `test_unwrapper.py` (57 tests).

The TOC and footnote vectors are the highest-value cases in the suite: a wrong verdict there
silently deletes a table of contents or drops a footnote block. They were ported from V1's
`.v1/defs/tests/test_false_tables.py`.

## Deliberate gaps

- **Unwrapping without metadata tracking is not exposed.** `cleanup_false_tables_with_metadata` is
  the canonical entry point; there is no metadata-free sibling, so full diagnostic lineage is
  preserved.
- **The private predicates stay private.** `_is_single_column_prose`, `_is_prose_marker`,
  `_is_unambiguous_list_marker`, `_is_prose_text`, `_marker_candidates`,
  `_wrapped_marker_candidates`, `_step_stack`, `_passes_monotonic`, `_is_ordered_prose_grid`, and
  `_visible_text` are ported unchanged. `_step_stack` exists because a single character in
  `ivxlcdm` is ambiguous between a roman numeral and a letter sequence (`i)` inside `g) h) i) j) k)`),
  and the ambiguity is resolved across the whole row sequence rather than per cell — a wrong
  resolution would silently drop a whole risk-factor list.
- **V1's lazy cover imports are gone, not moved.** V1 imported `defs.sec_forms.cover.structure` and
  the cover TOC vocabulary inside the function body to dodge a cycle, which hid a layer violation. In
  V2 that vocabulary lives in `edgar_sec.engine.tables.toc.patterns` — `RE_ITEM_REFERENCE`,
  `RE_PART_REFERENCE`, `RE_TOC_ITEM_ROW`, `RE_TOC_LEADER`, `RE_PAGE_SUFFIX`, `is_toc_row`,
  `looks_like_toc_row`, `looks_like_toc_tabular` — which is a leaf both this package and the cover
  boundary code import. `RE_PAGE_SUFFIX` is built from `PAGE_NUMBER_CORE`, which
  `foundation.text.patterns` already owns, so no page-marker module is imported.
- **Known defect carried over from V1:** `is_false_table` without geometry strips only the `<TABLE>`
  wrapper, so a body still carrying `<TR>`/`<TD>` never matches the leading-heading patterns and is
  classified as a false table. Callers pass rendered text, and geometry is preferred when available.