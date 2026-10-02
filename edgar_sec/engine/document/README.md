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
| `page_markers/models.py` | The 20 `PageMarkerKind` shapes, the label patterns, and the immutable analysis / marker / decision / artifact records. |
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

- `edgar_sec/engine/forms/normalize.py` — `prepare_input_text` (`unpacked`
  stage), then `html_project` → `page_policy` reaching `html/{breaks,normalizer}`
  and all of `page_markers/`, then `after_final_whitespace`. Also imports
  `is_page_marker_line` and `normalize_final_text_whitespace` directly.
- `edgar_sec/engine/forms/cover/` — `page_markers.units`
  (`body_start`, `body_context`), `page_markers.detector` (`boundary/detector`,
  `toc/finder`, `toc/analysis`, `toc/residue`, `reflow`, `healing/text`),
  `page_markers.models` (`models`), `page_markers.signatures` (`closing`).
- `edgar_sec/engine/reflow/` — `page_markers.signatures`
  (`engine/rewrapper`, `features/geometry`, `types`).
- `edgar_sec/engine/tables/ascii_html/` — `html.tree` (`converter`, `spans`,
  `renderer`, `model`, `quick_grid`).
- `edgar_sec/pipelines/document_storage/fetching.py` — `unpack_sgml_submission`,
  `has_sgml_documents`, `strip_pem_envelope`, `extract_target_sub_document`.
- `edgar_sec/pipelines/document_storage/delegation.py` — `SgmlSubDocument`,
  `unpack_sgml_submission`, `find_sub_document`, `has_sgml_documents`.
- `edgar_sec/pipelines/document_storage/review_artifacts.py` — `parse_html`.
- `edgar_sec/pipelines/document_storage/processor.py` — `PageMarkerAction`.

## Mirrored tests

| Test module | Covers |
| :--- | :--- |
| `tests/engine/document/unpacking/test_unpacker.py` | envelope unpacking, four-tier resolution, extraction, PEM, malformed input |
| `tests/engine/document/unpacking/test_representation.py` | decode ladder, envelope stripping, classification, stage order |
| `tests/engine/document/unpacking/test_ascii_pre.py` | PRE wrapper discrimination |
| `tests/engine/document/html/test_tags.py` | tag classification sets |
| `tests/engine/document/html/test_tree.py` | `parse_html`, traversal, mutation, text extraction |
| `tests/engine/document/html/test_cleaner.py` | the ordered passes plus the preservation side |
| `tests/engine/document/html/test_breaks.py` | sentinel injection and table exclusion |
| `tests/engine/document/html/test_normalizer.py` | projection, paragraph cohesion, table byte-preservation |
| `tests/engine/document/whitespace/test_normalizer.py` | padding, concatenated items, blank runs |
| `tests/engine/document/page_markers/test_models.py` | the shape vocabulary and analysis record |
| `tests/engine/document/page_markers/test_candidates.py` | contextual candidate scan and its guards |
| `tests/engine/document/page_markers/test_detector.py` | `analyze_page_markers`, `find_page_markers`, `is_page_marker_line` |
| `tests/engine/document/page_markers/test_sequence.py` | run validation and healing |
| `tests/engine/document/page_markers/test_units.py` | logical-unit classification |
| `tests/engine/document/page_markers/test_templates.py` | `analyze_repeating_headers` and window mechanics |
| `tests/engine/document/page_markers/test_artifacts.py` | token rendering and the sidecar |
| `tests/engine/document/page_markers/test_policy.py` | strip / annotate / preserve policy |
| `tests/engine/document/page_markers/test_signatures.py` | signature masking and healing |

Every module in this package has a mirrored test; the tree exists and is
collected by the committed suite. V1 parity is a development-time concern — the
V1 reference lives in the gitignored `.v1/` tree and has no committed harness.

## Deliberate gaps

- **Page-artifact metadata is built but discarded.** `build_page_artifact_metadata`
  is landed and tested with no caller: `NormalizationResult` has no field for the
  sidecar, and `normalize_document` binds `_artifacts`, `_templates`, `_next_id`
  to throwaways. Recording them is a change to the result record, which belongs
  to `engine/forms/normalize.py`.
- **`<noscript>` is not purged.** V1 removes exactly `<head>`, `<script>`, and
  `<style>`. An earlier V2 cleaner also removed `<noscript>`; that was
  divergence from the V1 production path rather than a fix, and was reverted.
- **Nothing here fetches.** No HTTP, no cache, no rate limiting — that is
  `edgar_sec/infra/sec_http`. This package starts from bytes already in hand.