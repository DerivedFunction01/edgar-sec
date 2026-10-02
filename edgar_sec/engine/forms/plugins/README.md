# `edgar_sec/engine/forms/plugins` — the form-family SPI and registry

Answers one question per document: *which family is this, and what should we do
about it before publishing?* Everything else in the engine is
representation-neutral; this is where the form's identity enters.

## Purpose

Filing behaviour is family-specific in exactly two places: whether a cover
exists and where it ends, and whether the document delegates to an exhibit
instead of carrying its own content. A 10-K states financials inline and
occasionally incorporates Exhibit 13 by reference; a 10-Q has no incorporated
reference block; an 8-K is an event report with neither. This package holds that
variance as data, so the normalization chain stays one chain.

## Layout

| Module | Responsibility |
| :--- | :--- |
| `base.py` | `FormPlugin` — the SPI record: canonical `family`, the `enable_toc` / `enable_body_start` gates, and the `evaluator` hook. Also `GENERIC_FAMILY` and `evaluate_generic`. |
| `registry.py` | The seeded family table, its module-level generic fallback, `get_plugin`, `register_plugin`, `registered_families`. |
| `evaluators/annual.py` | `evaluate_annual` — Exhibit 13 incorporation-by-reference detection. |
| `evaluators/quarterly.py` | `evaluate_quarterly` — XBRL-year and size-ceiling shortcuts. |
| `evaluators/current_report.py` | `evaluate_current_report` — unconditional proceed. |
| `__init__.py` | One-line docstring only. No re-exports, per AGENTS.md §1.2. |

## Contracts

- **Routing goes through `resolve_alias` and nothing else.** No substring test
  appears anywhere in the package. `10-K` vs `10-K405` and `10-Q` vs `10-Q/A`
  must not collide, and a substring router collides on both.
- **One plugin per family, not a chain of subclasses.** Four families are seeded —
  `10-K`, `20-F`, `10-Q`, `8-K` — each a frozen record, not a pipeline type.
- **`family` is the canonical key, not the raw input string.** `10-K405` and
  `10-K/A` select the same plugin; a consumer reading the un-canonicalized form
  has to redo the alias resolution to get the identity it already had.
- **The fallback is one shared frozen instance** with `family="GENERIC"`, both
  gates `False`, and `evaluate_generic`. `None`, `""`, `6-K`, `S-1`, `DEF 14A`,
  and anything unknown all resolve to it. It is deliberately not in the seeded
  table, so `registered_families()` reports only the four real families.
- **`register_plugin` is process-global and irreversible.** The table is module
  state, visible to every thread and every later resolution; there is no
  unregister, so an overriding test must restore the prior entry itself. An
  override registered under a raw form string that resolves to a seeded family is
  shadowed and has no effect, because resolution consults the family first.
- **20-F is annual for normalization and generic for triage.** It carries the
  annual stage gates but `evaluate_generic`, so an Exhibit 13 delegation in a
  foreign annual report is not detected as a stub. Preserved deliberately;
  pinned by `test_twenty_f_is_annual_for_normalization_and_generic_for_triage`.
- **`enable_toc` / `enable_body_start` gate real stages.** A plugin whose flags are
  wrong silently returns text with a TOC still in it.

## Public surface

- `FormPlugin`, `GENERIC_FAMILY`, `evaluate_generic` — `base.py`.
- `register_plugin`, `registered_families`, `get_plugin` — `registry.py`.
- `evaluate_annual` — `evaluators/annual.py`.
- `evaluate_quarterly`, `HTML_SIZE_CEILING`, `ASCII_SIZE_CEILING` —
  `evaluators/quarterly.py`.
- `evaluate_current_report` — `evaluators/current_report.py`.

## Command surface

None. Library package, no CLI.

## Production consumers

- `edgar_sec/pipelines/document_storage/processor.py` — `get_plugin`, then
  `plugin.evaluator(result.text)`.

Because the evaluator is real, `FilingProcessor.process` writes five metadata
keys it would otherwise not — `is_stub`, `category`, `decision_action`,
`decision_reason`, `target_exhibit` — and populates `ProcessedDocument.decision`.
`metadata` is a free-form mapping with no column schema, so nothing breaks, but
the stored snapshot gains those fields.

## Tests

`tests/engine/forms/plugins/test_base.py`,
`tests/engine/forms/plugins/test_registry.py`, and
`tests/engine/forms/plugins/evaluators/test_annual.py`, `test_quarterly.py`,
`test_current_report.py`.

## Deliberate gaps

- **The evaluators' context arguments are unreachable.** The SPI is
  `plugin.evaluator(result.text)` — one positional argument — and no production
  caller supplies more. So `evaluate_annual`'s XBRL year shortcut and
  `evaluate_quarterly`'s `filing_year` / `raw_length` / `is_html` shortcuts
  cannot fire in production, even though all three are live in the port.
  **Closing this requires a caller change** (`FilingProcessor` passing context),
  not a port change.
- **The delegation verb list is windowed, not anchored.** Eleven delegation
  verbs are searched in a ±300-character window around *any* Exhibit 13 mention,
  so an exhibit-index row sitting beside "as referred to in the notes" can
  produce `refetch_sub_doc`. Tightening it would reclassify already-stored
  documents, so the false-positive surface is preserved deliberately.
- **`line_num` is the anchor's line, not the delegation's**, so the reported line
  can be up to 300 characters from the quoted reason. Pinned by
  `test_the_reported_line_is_the_anchors_line_not_the_verbs`.
- **`DecisionAction.SKIP_HARD_STUB` is never emitted** by any evaluator. Present
  in the vocabulary, unused in behaviour.
- **`ContentTransform` has no reader.** The alias is declared in
  `edgar_sec/domain/forms/common/models.py` with zero references; no
  `transform_content` hook exists in this package.
- **No per-family taxonomy lookup here.** Per-family vocabulary reaches consumers
  as `CoverProfile.derived_taxonomy` from `engine/forms/cover/profiles.py`. The
  plugin lookup and the cross-family aggregate do not exist.
