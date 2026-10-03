# `edgar_sec/engine/forms` — document normalization

Composes filing document parsing and normalization and returns the result record.

## Purpose

Normalization combines document preparation, page policy, cover analysis, table
handling, and representation-specific reflow.

## Layout

| Module | Responsibility |
| :--- | :--- |
| `normalize.py` | `normalize_document`, `NormalizationResult`, and stage orchestration. |
| `cover/` | The cover decision chain — boundary, TOC, cover tables, healing, checkmarks, closing, profiles. See `cover/README.md`. |
| `plugins/` | The `FormPlugin` SPI, the family registry, and the per-family evaluators. See `plugins/README.md`. |
| `__init__.py` | Docstring only. No re-exports, per AGENTS.md §1.2. |

## Contracts

- **Stage order is owned by `normalize.py`.** See its docstring for the current
  composition sequence.
- **Changed text stages may record output identity metadata** using
  `StageRecord` from `domain/forms/common/models.py`.
- **Cover positions use distinct coordinate spaces.**
  `cover_boundary_detected_line` refers to pre-reflow text;
  `cover_boundary.end_line` refers to final text.
- **`normalize_document` never raises on malformed input.** Every stage is
  total; a payload that fails classification still produces a result.
- **No shims, no barrel re-exports.** Consumers import leaf modules.
- **Layer discipline.** This package imports `domain`, `engine.*`, and
  `foundation`. Enforced by the `layer-boundary` scanner.

## Public surface

- `normalize_document`, `NormalizationResult` — `normalize.py`.
- `StageRecord` — `edgar_sec/domain/forms/common/models.py`.
- The cover and plugin surfaces — see each package's README.

## Command surface

None. Library package, no CLI.

## Tests

Mirrored coverage lives under `tests/engine/forms/`.

## Deliberate gaps

- **No page-artifact metadata is included in `NormalizationResult`.**
- **Evaluators receive text only.** The optional evaluator context is not supplied;
  see `plugins/README.md`.
- **HTML payloads do not use ASCII reflow.**
