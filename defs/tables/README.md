# `defs/tables/` — Shared Table Processing

Provides the phase-independent table contract used by document normalizers.
The primary table engine is `ascii_html`, a geometry-first presentation layer
that resolves 2D cell coordinate grids, rowspan/colspan regions, border dividers,
affix fusion, and balanced column width budgeting to render standardized SEC
`<TABLE>` blocks.

`render_grid_to_ascii` formats programmatic 2D matrix grids directly using the same
geometry and budgeting rules without needing an HTML DOM.

`protection.py` owns exact tagged-table protection for plain-text pipelines:
`mask_tagged_tables()` replaces complete — and unterminated, through
end-of-text — `<TABLE>...</TABLE>` spans with collision-safe sentinels so
whitespace-oriented passes cannot see their layout, and
`restore_tagged_tables()` restores the original bytes exactly. A source that
already contains the sentinel byte is returned unmasked; callers must treat
that as "no reflow possible".

> [!NOTE]
> **TODO: Future Table Unwrapping / De-Tabling Policy**
> Many SEC HTML filings use `<table>` tags for non-tabular layout purposes (such as
> 1x1 container boxes, vertical 1-column paragraph stacks, bullet lists wrapped in `<td>`,
> or key-value metadata pairs). When de-tabling is implemented in a future phase,
> tables should only be unwrapped to plain text/markdown when strict invariants hold:
> - The table must contain zero financial/numeric data cells (`is_numeric_cell == False`).
> - The table must not contain multi-column matrix data or visual border rules.
> - Tables matching whitelisted non-data layout shapes (single-cell containers, 1-col stacks,
>   2-col bullet lists, or 2-col key-value pairs) may be unwrapped to prose/lists, while
>   all multi-dimensional data tables remain canonical `<TABLE>` blocks.

The public API is exported from `defs.tables`. Contract tests live in
`defs/tests/test_ascii_html.py`, `defs/tests/test_table_protection.py`, and
`defs/tests/test_table_protection.py`.

The manually reviewed table corpus is stored as the single tracked Parquet
fixture `defs/tests/fixtures/tables/validated_table_corpus_v2.parquet`. The
one-off builder is `defs/tests/build_table_corpus.py`; it reads local
scratch/source files and is never invoked by the default tests. Corpus
comparison reports are generated under `.artifacts/test-runs/defs/table-goldens/`.

Use `PYTHONPATH=. .venv/bin/python defs/tests/query_table_corpus.py --grep
"Hedged items" --corpus jnj_2025 --context 3` to locate reviewed output, or
select an exact ID with `--id` and inspect it using `--head`, `--tail`, or
`--offset`. Searches cover both source HTML and expected output by default;
use `--search-in html` or `--search-in expected` to restrict the field.
To compare directly against the `ascii_html` renderer, use `--show side-by-side`
(side-by-side column view), `--show diff` (unified diff), or `--show v2`.

For a single readable file containing every converted table and its source
metadata, run `PYTHONPATH=. .venv/bin/python defs/tests/dump_table_corpus.py`.
The default output is a generated file under `.artifacts/test-runs/`; use
`--corpus jnj_2025` to limit the dump or `--output -` to write to stdout.
The dump utility renders source HTML with `ascii_html`; `--v2` remains
available as an explicit spelling for scripts that compare renderer modes.
To generate a comprehensive comparison across the corpus, use `--side-by-side`
or `--diff`.
The live v2 corpus starts schema-only. Promote reviewed tables explicitly with
`PYTHONPATH=. .venv/bin/python defs/tests/promote_table_corpus.py --id TABLE_ID`.
Promotion recomputes the expected render from the stored raw HTML using the
current converter.
Use `--all-corpus CORPUS --exclude-file FILE` to promote a reviewed corpus
except for tracked failure or not-applicable ID lists.
Approved ID lists can also be promoted with `--ids-file FILE`.
Horizontal-layout review candidates are tracked in
`defs/tests/fixtures/tables/review_fail_jpmorgan_horizontal_first_100.txt`.

For source-first review of selected tables, run
`PYTHONPATH=. .venv/bin/python defs/tests/build_table_review_artifacts.py`
with one or more `--id` values. Each generated artifact contains the original
HTML, pipeline diagnostics, and current ASCII render.
Use `--corpus jnj_2025` or `--all` to generate a batch. Batches also include a
`review_manifest.jsonl` with one row per table and blank `status`, `pattern`,
`issues`, `evidence`, and `recommendation` fields for programmatic review.
Use `chunk_table_reviews.py` to split a manifest into fixed-size agent batches;
for example, `--limit 100 --size 20` creates five batches for the first 100
tables.
For the review loop, `dump_table_review_set.py --ids-file FILE --output FILE`
renders only the listed failures from raw HTML into one source-first file for
visual approval.
The dump utility also accepts `--whitelist` and `--blacklist` newline-delimited
ID files, plus `--limit`, so reviewed PASS candidates can be inspected without
changing the corpus. The confirmed first-100 failure list is tracked at
`defs/tests/fixtures/tables/review_fail_first_100.txt`.

### Table scope contract

`templates/scope.py` defines `TableScope`, a typed capability selector retained
for form and taxonomy classification. It does not select a renderer; all HTML
tables use the geometry-first engine.

- `TableScope.BODY` — body-table classification
- `TableScope.TOC` — table-of-contents classification
- `TableScope.COVER` — cover-table classification
