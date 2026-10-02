# `edgar_sec/engine/forms` — the composition seam

Owns **stage order and the result record, and nothing else**. Every algorithm
lives in a leaf package: `engine.document` for input preparation, HTML, page
markers, and whitespace; `engine.tables` for table handling; `engine.reflow` for
conservative ASCII reflow; `engine.forms.cover` for the cover decision chain;
`engine.forms.plugins` for family routing and triage. `normalize.py` re-declares
no type — each result type is declared where it is produced and imported here.

## Purpose

The order of the transformation chain is the contract. HTML cleaning must
precede table rendering; page policy must precede reflow so reflow does not
rewrite page furniture; the cover boundary must be detected *before* reflow
because reflow shifts line numbers. Getting that order wrong produces output that
is plausible and wrong, with the symptom far from the cause.

## Layout

| Module | Responsibility |
| :--- | :--- |
| `normalize.py` | `normalize_document`, `NormalizationResult`. Sole owner of stage order. |
| `cover/` | The cover decision chain — boundary, TOC, cover tables, healing, checkmarks, closing, profiles. See `cover/README.md`. |
| `plugins/` | The `FormPlugin` SPI, the family registry, and the per-family evaluators. See `plugins/README.md`. |
| `__init__.py` | Docstring only. No re-exports, per AGENTS.md §1.2. |

## Contracts

- **Stage order is load-bearing.** See the table below.
- **Most stages record a `StageRecord`** carrying its own output digest, line
  count, and character count. A stage *name* cannot localize a divergence; the
  first record whose `text_identity` differs is the first stage that behaved
  differently. `StageRecord` lives at Layer 0 because that is the only place the
  producer and both pipeline consumers can import from without a layer violation.
- **The cover boundary is detected before reflow.** Reflow collapses blocks and
  shifts line numbers, so `cover_boundary_detected_line` is a pre-reflow
  coordinate and is stable; `cover_boundary.end_line` is in final-text
  coordinates and may have moved.
- **`normalize_document` never raises on malformed input.** Every stage is
  total; a payload that fails classification still produces a result.
- **No shims, no barrel re-exports.** Consumers import leaf modules.
- **Layer discipline.** This package imports `domain`, `engine.*`, and
  `foundation`. Enforced by the `layer-boundary` scanner.

## The stage order

| # | Stage | Branch | What it does |
| ---: | :--- | :--- | :--- |
| 1 | `unpacked` | always | Encoding ladder (UTF-8 → CP1252 → Latin-1), PEM/SGML envelope stripping, ASCII-PRE discrimination, representation classification. |
| 2 | `html_cleaned` | HTML | `<pre>` masking, table rendering with geometry retention, false-table unwrapping, structural projection. |
| 3 | `page_policy` | always | Page-furniture detection in the text frame and the strip policy. |
| 4 | `cover_boundary` | always | Multi-signal cover boundary from the family profile. |
| 5 | `after_yes_no_pair_normalization` | pair changed | Authoritative normalization for complete inline Yes/No pairs. |
| 6 | `after_checkmark_rewrite` | checkmark changed | Checkbox candidate extraction, constraint solving, and decision application. |
| 7 | `after_cover_table_cleaning` | table changed | Form-governed cover pseudo-table unwrapping inside the boundary. |
| 8 | `after_cover_healing` | cover changed | Bounded cover text healing with table masking and binary-block merging. |
| 9 | `after_final_whitespace` | always | Final whitespace normalization and blank collapse. |
| 10 | `before_reflow` / `after_reflow` | ASCII | Conservative ASCII reflow after body start, with line coordinate mapping. |
| — | TOC, body start, closing | profile-gated | Detection-only. They populate `toc_span`, `body_start`, and `closing_span` without mutating text and **record no `StageRecord`**. |

`toc_span` and `body_start` are gated on the profile declaring a `boundary` and
the matching signals; `closing_span` always runs, searching from after the body
start.

## Public surface

- `normalize_document`, `NormalizationResult` — `normalize.py`.
- `StageRecord` — `edgar_sec/domain/forms/common/models.py`.
- The cover and plugin surfaces — see each package's README.

## Command surface

None. Library package, no CLI.

## Production consumers

- `edgar_sec/pipelines/document_storage/processor.py` — `normalize_document`, plus
  the form evaluator via `get_plugin`.
- `edgar_sec/pipelines/document_storage/review_artifacts.py` — the result's
  geometry, stage trace, and page analysis.

## Tests

- `tests/engine/forms/test_normalize.py`
- `tests/engine/forms/cover/**` and `tests/engine/forms/plugins/**`
- `tests/pipelines/document_storage/test_worker.py` — the chain end to end.

## Deliberate gaps

- **No page-artifact sidecar is emitted.** `build_page_artifact_metadata` is
  landed and tested but has no caller: `NormalizationResult` has no field for it,
  and inventing one is a design decision rather than a restoration.
- **The evaluator's context arguments are never supplied.** `FilingProcessor`
  calls `plugin.evaluator(result.text)`, so the metadata shortcuts behind
  `evaluate_annual` and `evaluate_quarterly` cannot fire — see
  `plugins/README.md`.
- **HTML payloads skip reflow entirely.** `reflow_ascii` runs only when
  `representation is not HTML`, so `NormalizationResult.reflow` is `None` for
  every HTML filing.
