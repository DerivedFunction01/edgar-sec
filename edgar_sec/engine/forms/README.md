# `edgar_sec/engine/forms` — document normalization

Composes filing document parsing and normalization and returns the result record.

## Purpose

Normalization combines document preparation, page policy, cover analysis, table
handling, and representation-specific reflow.

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
- **A binary route is refused, not normalized.** `NormalizationResult` holds only
  text, and a PDF has none to hold and is deferred on text extraction.
- **`document_path` selects the route, and the payload decides markup.** The route
  from `domain/document/route.py` decides which stages are eligible and supplies the
  representation only where the payload cannot show it — an XML-native document
  carries no HTML discriminator. For markup the bytes decide, so a `.htm` path whose
  payload has no markup is still normalized as ASCII.
- **No prose reflow for markup, XML, binary, or paper.** Only the text routes enter
  the reflow gate, and a paper stub returns before any form-driven stage runs.
- **A no-cover profile is `GENERIC`, never `boundary is None`.** Every profile
  carries a boundary policy, so `None` is not a test that can distinguish one.
- **No shims, no barrel re-exports.** Consumers import leaf modules.
- **Layer discipline.** This package imports `domain`, `engine.*`, and
  `foundation`. Enforced by the `layer-boundary` scanner.

## Command surface

<!-- AUTOGEN:COMMANDS:START -->
<!-- AUTOGEN:COMMANDS:END -->

## Deliberate gaps

- **No page-artifact metadata is included in `NormalizationResult`.**
- **Evaluators receive text only.** The optional evaluator context is not supplied;
  see `plugins/README.md`.
- **HTML payloads do not use ASCII reflow.**
- **Most form families are unmodelled.** Cover profiles exist for six families; every
  other form resolves to `GENERIC` with the generic plugin, so a family with real
  cover structure gets no cover-aware handling until it is modelled.
