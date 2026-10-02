"""Geometry-first ASCII table renderer for SEC HTML tables.

`converter.py` is the entry point: `convert_html_tables_to_ascii_with_metadata`
parses a document once, converts each top-level table, and returns the rendered
text alongside one `TableGeometry` per table that produced output. The rest of
the package is that conversion staged so each decision has one owner — spans in
`spans.py`, width in `widths.py` and `balance.py`, dividers in `dividers.py`.

See `README.md` for the contracts and the deliberate gaps.
"""
