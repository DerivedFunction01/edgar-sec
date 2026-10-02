# `edgar_sec/engine/forms/cover/toc` — table-of-contents span detection

Finds the exclusive source span containing a filing's table of contents, so the
boundary stage knows where the cover ends and the body begins.

## Purpose

The finder runs a strict ladder and returns the first method that reaches its row
minimum. That ordering is the package's central guarantee: a heading-led TOC is
never reported as the weaker density or aligned-row forms, because a caller
reading `method` can trust that `heading_rows` means a heading *and* rows were
both found.

## Layout

| Module | Responsibility |
| :--- | :--- |
| `finder.py` | The method ladder, table-boundary claiming, and end refinement. |
| `analysis.py` | Row gathering, block density, and the late-item anachronism test. |
| `residue.py` | Consumes trailing TOC residue until substantive prose begins. |
| `patterns.py` | TOC-block-specific regex vocabulary. |
| `models.py` | `TocSpan` and `TocEvidence`. |
| `__init__.py` | One-line docstring only. No re-exports, per AGENTS.md §1.2. |

`finder.py` depends on `analysis.py`, `residue.py`, `patterns.py`, and
`models.py`; `residue.py` depends on `analysis.py` and `patterns.py`. Nothing in
this package imports `finder.py`.

## Contracts

- Methods, strongest first: `heading_rows`, `weak_heading_rows`,
  `tagged_table_merged`, `tagged_table`, `density_score`,
  `anachronism_late_item`, `aligned_rows`.
- Only `aligned_rows` sets `approximate=True`. Every other method is a positive
  identification.
- A `TABLE OF CONTENTS` heading whose rows start more than ten lines later is
  mid-document navigation text, not a TOC start, and is not returned.
- A table boundary is claimed only when the last TOC row still sits inside an
  open `<TABLE>` region whose close falls inside the search limit.
- A page-break-split continuation table is merged and reported as
  `tagged_table_merged` with `"merged across page break"` in the boundary
  evidence. A single table never carries that text.
- End refinement runs in two passes: aligned residue past the claimed boundary is
  absorbed first, then a PART/ITEM sequence reset truncates the span. The reset
  evidence row names the line where the span was cut.
- `start_offset` and `end_offset` are character offsets into the same string
  `start_line` and `end_line` index into.

## Public surface

- `find_toc_span(text, *, start_line=0, max_lines=None, minimum_rows=2, derived_taxonomy=None, page_analysis=None) -> TocSpan | None` — `finder.py`.
- `consume_toc_residue(lines, start_index, limit, derived_taxonomy=None, page_marker_lines=None) -> int` — `residue.py`.
- `normalize_for_matching`, `is_anachronistic_late_item`, `score_block_toc_density` — `analysis.py`.
- `is_toc_row`, `looks_like_toc_row`, `looks_like_toc_tabular` — re-exported from `analysis.py`; declared in `edgar_sec.engine.tables.toc.patterns`.
- `TocSpan`, `TocEvidence` — `models.py`.
- `RE_TOC_HEADING`, `RE_TOC_ITEM`, `RE_TOC_PART_ROW`, `RE_TOC_PART_TEXT`, `RE_TOC_NUMERIC_LABEL`, `WEAK_TOC_HEADINGS` — `patterns.py`.

## Command surface

None. Library package, no CLI.

## Tests

- `tests/engine/forms/cover/toc/test_models.py`
- `tests/engine/forms/cover/toc/test_patterns.py`
- `tests/engine/forms/cover/toc/test_analysis.py`
- `tests/engine/forms/cover/toc/test_residue.py`
- `tests/engine/forms/cover/toc/test_finder.py`

## Deliberate gaps

- **The row predicates are not declared here.** `is_toc_row`,
  `looks_like_toc_row`, `looks_like_toc_tabular`, `RE_TOC_ITEM_ROW`,
  `RE_TOC_LEADER`, `RE_PAGE_SUFFIX`, `RE_PART_REFERENCE`, and `RE_ITEM_REFERENCE`
  live in `edgar_sec.engine.tables.toc.patterns` and are imported. Table
  classification refuses the same rows, and the two sides must agree on what a
  TOC row is; a second copy would drift.
- **`derived_taxonomy` is duck-typed, not modelled.** A caller may pass a plain
  dict of vocabulary strings, or one carrying a `matcher` object that answers
  `has_any()` and `find_matches()`. Neither shape is validated here, and a dict
  missing a key silently falls back to the default vocabulary.
- **`INDEX` and `REFERENCE(S)` are treated as TOC headings only when rows
  corroborate them.** A real index in the back of a filing is therefore reported
  as a TOC. The cover stage only scans the front of the document, so this does
  not arise there, but a caller scanning later text will get a false positive.
- **No body-boundary side.** The span's `end_line` is where the TOC stops, not
  where the body starts; body resolution is a separate stage.
