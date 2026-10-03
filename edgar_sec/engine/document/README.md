# `edgar_sec/engine/document` — input preparation, HTML normalization, page furniture

Input preparation, HTML reduction to text, page-marker detection and policy, and
the final whitespace pass. Pure: no network I/O, no artifact writes, no stage
ordering — the stage order belongs to `edgar_sec/engine/forms/normalize.py`.

## Purpose

An EDGAR payload arrives as a `.txt`/`.nc` SGML bundle, hand-authored HTML, or —
for a large share of 1990s–2000s filings — plain ASCII inside a `<PRE>` wrapper.
Before anything can reason about one it must be decoded, unwrapped, classified,
cleaned, projected, and had its page furniture resolved.

## Layout

| Module | Responsibility |
| :--- | :--- |
| `unpacking/unpacker.py` | SGML `<DOCUMENT>` envelope unpacking; four-tier target resolution; PEM wrapper removal. |
| `unpacking/representation.py` | `prepare_input_text` — decode ladder, envelope stripping, representation classification, HTML cleaning dispatch. |
| `unpacking/ascii_pre.py` | `extract_ascii_pre` — PRE-wrapper discrimination. |
| `html/tags.py` | The tag classification vocabulary every other `html` module shares. |
| `html/tree.py` | `selectolax` DOM surface: `parse_html`, `FastHtmlNode`, `FastHtmlTree`. |
| `html/cleaner.py` | Stage-1 cleaning passes plus `strip_non_displaying_blocks`. |
| `html/breaks.py` | Page-break sentinel injection outside `<TABLE>` spans; the composed projection entry point. |
| `html/normalizer.py` | HTML-to-text projection: `normalize_html_document`, `decompose_html_structures`. |
| `whitespace/normalizer.py` | Final whitespace pass: line-end padding, concatenated list items, blank-run collapse. |
| `page_markers/models.py` | The `PageMarkerKind` shapes, the label patterns, and the immutable analysis / marker / decision / artifact records. |
| `page_markers/candidates.py` | Contextual candidate scan plus the geometry and prose guards that keep a table from reading as a page sequence. |
| `page_markers/detector.py` | `analyze_page_markers` — the ordered scan that composes the modules below. |
| `page_markers/sequence.py` | Run validation and conservative healing. |
| `page_markers/units.py` | `LogicalUnit` / `classify_units` — blank-line block classification. |
| `page_markers/templates.py` | `analyze_repeating_headers` and its window, clustering, and merge mechanics. |
| `page_markers/artifacts.py` | The `[[SEC:KIND id=N]]` token, template normalization and ids, the sidecar. |
| `page_markers/policy.py` | `apply_page_markers` and its text-frame / projected-HTML entry points. |
| `page_markers/signatures.py` | Signature-region location, line-count-preserving mask/restore, letter-spaced name healing. |

Subpackage READMEs: [`html/`](html/README.md), [`page_markers/`](page_markers/README.md),
[`unpacking/`](unpacking/README.md), [`whitespace/`](whitespace/README.md).

## Contracts

- **`prepare_input_text` stage order is load-bearing**: decode → strip envelopes
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

## Public surface

```python
from edgar_sec.engine.document.unpacking.unpacker import unpack_sgml_submission
from edgar_sec.engine.document.unpacking.representation import prepare_input_text
from edgar_sec.engine.document.unpacking.ascii_pre import extract_ascii_pre
from edgar_sec.engine.document.html.tree import parse_html
from edgar_sec.engine.document.html.cleaner import clean_html_for_parsing
from edgar_sec.engine.document.html.breaks import render_html_to_break_text
from edgar_sec.engine.document.html.normalizer import normalize_html_document
from edgar_sec.engine.document.whitespace.normalizer import (
    normalize_final_text_whitespace,
)
from edgar_sec.engine.document.page_markers.detector import analyze_page_markers
from edgar_sec.engine.document.page_markers.policy import apply_text_policy
```

Per-module surfaces are in the subpackage READMEs.

## Command surface

None. Library package, no CLI.

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

## Mirrored tests

`tests/engine/document/` mirrors this tree package-for-package (`unpacking/`,
`html/`, `whitespace/`, `page_markers/`), with a test module per source module.
The committed suite is the only executable record of the package's behaviour.

## Deliberate gaps

- **`<noscript>` is not purged.** `strip_non_displaying_blocks` removes `<head>`,
  `<script>`, and `<style>` only, so no-script fallback text — content a reader
  sees with scripting off — stays in the frame.
- **Nothing here fetches or writes.** No network, no artifact writes: this
  package starts from bytes already in hand, and retrieval is
  `edgar_sec/infra/sec_http`.