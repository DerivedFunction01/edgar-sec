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

The manually reviewed Apple, JPMorgan, JNJ, Berry, and Kellogg table corpus is
stored as the single tracked Parquet fixture
`defs/tests/fixtures/tables/validated_table_corpus.parquet`. The one-off builder
is `defs/tests/build_table_corpus.py`; it reads local scratch/source files and
is never invoked by the default tests. Corpus comparison reports are generated
under `.artifacts/test-runs/defs/table-goldens/`.

Use `PYTHONPATH=. .venv/bin/python defs/tests/query_table_corpus.py --grep
"Hedged items" --corpus jnj_2025 --context 3` to locate reviewed output, or
select an exact ID with `--id` and inspect it using `--head`, `--tail`, or
`--offset`. Searches cover both source HTML and expected output by default;
use `--search-in html` or `--search-in expected` to restrict the field.
