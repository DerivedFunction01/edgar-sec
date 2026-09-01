# `defs/tables/` — Shared Table Processing

Provides the phase-independent table contract used by document normalizers.
`convert_html_tables_to_ascii` parses visual HTML tables, removes non-visual
content, resolves `rowspan`/`colspan`, unwraps layout tables, heals split
currency and footnote columns, and renders standardized SEC `<TABLE>` blocks.

`HTMLTableConverter` also accepts an already-resolved grid for callers that
need direct formatting, while `GenericTable` owns wrapping, widths, alignment,
and `<S>`/`<C>` marker output. `SimpleTableProcessor` handles parsing and
repairs for generated ASCII tables.

The public API is exported from `defs.tables`. Contract tests live in
`defs/tests/test_tables.py` and are run independently from phase test suites.

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

For a single readable file containing every converted table and its source
metadata, run `PYTHONPATH=. .venv/bin/python defs/tests/dump_table_corpus.py`.
The default output is a generated file under `.artifacts/test-runs/`; use
`--corpus jnj_2025` to limit the dump or `--output -` to write to stdout.
To preview the current converter rather than the stored expected output, add
`--render-current`; this converts each raw HTML table from the Parquet corpus
at dump time.
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

### Cover table templates

`templates/cover.py` provides cover-page layout decomposition:
- `cover_layout_template` — decomposes address, state, EIN, contact tables into prose blocks
- `checkbox_grid_template` — formats filer-category and yes/no checkbox grids
- `single_row_horizontal_template` — joins single-row multi-cell layout blocks

These templates consume canonical label matchers from `defs.sec_forms.cover.vocabulary` and are scoped to cover-page tables via the typed `TableScope.COVER` in the template dispatcher. Body and data tables use the generic table converter.

### Table scope contract

`templates/scope.py` defines `TableScope`, a typed capability selector for the
dispatcher. It is deliberately form-name agnostic: SEC form families select
scopes, they do not branch inside the shared table layer.

- `TableScope.BODY` — generic financial and body templates
- `TableScope.TOC` — table-of-contents tables; body templates disabled
- `TableScope.COVER` — cover and registration templates plus body templates

`apply_table_templates` accepts a `TableScope` or a legacy string. A no-cover
scope cannot activate registration, cover-layout, or cover-checkbox templates.
