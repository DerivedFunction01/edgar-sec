# `edgar_sec/engine/document` — input preparation, HTML normalization, page furniture

Input preparation, HTML reduction to text, page-marker detection and policy, and
the final whitespace pass. Pure: no network I/O, no artifact writes, no stage
ordering — the stage order belongs to `edgar_sec/engine/forms/normalize.py`.

## Purpose

An EDGAR payload arrives as a `.txt`/`.nc` SGML bundle, hand-authored HTML, or —
for a large share of 1990s–2000s filings — plain ASCII inside a `<PRE>` wrapper.
Before anything can reason about one it must be decoded, unwrapped, classified,
cleaned, projected, and had its page furniture resolved.

## Contracts

- **`prepare_input_text` stage order is important**: decode → strip envelopes
  → purge non-displaying blocks → test for ASCII-PRE → classify → clean.
  Purging first stops a `<script>` outside a `<PRE>` reading as content; testing
  ASCII-PRE before HTML cleaning is what preserves the hard line breaks ASCII
  reflow depends on.
- **Nothing raises on malformed input.** Public functions return `""`, `[]`,
  `None`, or a wrapper. `unpack_sgml_submission("")` returns `[]`;
  `extract_ascii_pre("<pre>a</pre><pre>b</pre>")` returns `None`.
- **`<TABLE>` bytes survive HTML projection byte-for-byte** — tables are masked
  before entity unescaping. See
  [`engine/tables/protection/`](../tables/protection/README.md).
- **Break markup inside a table is never converted.** A decorative `<hr>` row
  rule would become a sentinel the ASCII table renderer then wraps as cell text.
- **Wrappers are `__slots__`-only and hold no parsed state.** `node.parent`
  returns a fresh wrapper, so compare with `==`, never by identity.
- **No barrel re-exports.** Every `__init__.py` is a docstring.
- **Layer discipline.** Imports only `foundation`, `domain`, and `engine.tables`.

## Command surface

<!-- AUTOGEN:COMMANDS:START -->
<!-- AUTOGEN:COMMANDS:END -->

## Production consumers

- `edgar_sec/engine/forms/normalize.py` — the `unpacked`, `page_policy`, and
  `after_final_whitespace` stages of `normalize_document`.
- `edgar_sec/engine/forms/cover/` — cover boundary, TOC, reflow, healing, body
  start, and closing, all over `page_markers/`.
- `edgar_sec/engine/reflow/` and `edgar_sec/engine/tables/ascii_html/` —
  signature masking and the `html.tree` wrappers respectively.
- `edgar_sec/pipelines/document_storage/` — envelope unpacking and delegation
  (`fetching`, `delegation`), `parse_html` for review artifacts, and
  `PageMarkerAction` for the processor.

## Deliberate gaps

- **`<noscript>` is not purged.** `strip_non_displaying_blocks` removes `<head>`,
  `<script>`, and `<style>` only, so no-script fallback text — content a reader
  sees with scripting off — stays in the frame.
- **Nothing here fetches or writes.** No network, no artifact writes: this
  package starts from bytes already in hand, and retrieval is
  `edgar_sec/infra/sec_http`.
