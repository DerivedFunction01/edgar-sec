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
