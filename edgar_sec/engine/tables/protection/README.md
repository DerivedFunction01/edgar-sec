# `edgar_sec/engine/tables/protection` — byte-exact `<TABLE>` span masking

The leaf every masking consumer shares. Legacy ASCII/SGML filings carry `<TABLE>…</TABLE>` blocks
marked up with `<S>`/`<C>` cell delimiters; those blocks are alignment-sensitive, so reflowing one
scrambles every column. This package masks each span behind a collision-safe sentinel so later
prose-rewriting passes cannot see inside it, then restores the exact original bytes.

## Purpose

Answer two questions for the rest of the engine: *which byte ranges are a table*, and *can you hand
me those bytes back unchanged*. Nothing here decides where a table begins semantically, converts
HTML to a grid, or unwraps a layout table — those are the sibling modules in `engine/tables/`.

## Contracts

- **Restoration is byte-for-byte and verified.** `restore_tagged_tables` reinstates the exact span
  text, and raises `ValueError` when the sentinels observed do not equal the spans supplied — a
  document that quietly lost a table is worse than a failed one.
- **Masking is a no-op on a document with no tables, and on one already holding a sentinel.**
  `find_table_spans` returns `()` when `SENTINEL_PREFIX` is present, so double-masking nests nothing.
- **An unclosed `<TABLE>` is protected through end-of-text** and reported as not `.complete`.
- **Tags match case-insensitively.** `<table>` / `</Table>` produce the same spans as uppercase SGML.
- **Masked offsets are not source offsets.** A sentinel is longer than the single-digit index it
  replaces, so offsets drift from the first span onward. `_masked_sentinel_starts` resolves true
  masked positions; slicing masked text with `span.start` is wrong.
- **Standard library only.** Enforced by the `layer-boundary` scanner. No I/O, no settings reads.

## Command surface

<!-- AUTOGEN:COMMANDS:START -->
<!-- AUTOGEN:COMMANDS:END -->

## Production consumers

- `engine/document/html/breaks.py` — `find_table_spans`, to keep page-break sentinels out of tables.
- `engine/document/html/normalizer.py`, `engine/document/whitespace/normalizer.py` — mask/restore.
- `engine/forms/cover/healing/text.py` — mask/restore around cover healing.
- `engine/forms/cover/checkmarks/{rewrite,candidates,frames}.py` — mask/restore plus masked-offset
  translation.
- `engine/forms/cover/toc/finder.py`, `engine/forms/cover/boundary/corridor.py` — the tag patterns.
- `engine/reflow/types.py`, `engine/reflow/features/context.py`, `engine/reflow/engine/rewrapper.py` —
  `TableSpan`, the tag patterns, and mask/restore plus `ensure_table_tag_boundaries`.
- `engine/tables/policy/intro.py` — the sentinel prefix, to refuse to reunite prose across a table.

## Deliberate gaps

- **No HTML-level masking.** This package masks `<TABLE>` spans in plain text. HTML `<table>`
  conversion and geometry belong to `engine/tables/ascii_html/`; fixed-width `<pre>` masking to
  `engine/tables/hybrid/`.
- **No table detection.** It finds spans that are *already tagged*. It will not decide that untagged
  aligned columns constitute a table; that is `engine/tables/resolver.py`'s job.
- **No filesystem, no network, no CLI.**
