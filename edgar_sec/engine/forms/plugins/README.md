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

## Command surface

<!-- AUTOGEN:COMMANDS:START -->
<!-- AUTOGEN:COMMANDS:END -->

## Production consumers

- `edgar_sec/pipelines/document_storage/processor.py` — `get_plugin`, then
  `plugin.evaluator(result.text)`. The resulting decision adds `is_stub`,
  `category`, `decision_action`, `decision_reason`, and `target_exhibit` to the
  stored metadata and populates `ProcessedDocument.decision`.

## Deliberate gaps

- **The evaluators' context arguments are unreachable.** The SPI is
  `plugin.evaluator(result.text)` — one positional argument — and no production
  caller supplies more. So `evaluate_annual`'s XBRL year shortcut and
  `evaluate_quarterly`'s metadata shortcuts cannot fire in production.
  **Closing this requires a caller change** (`FilingProcessor` passing context),
  not a change to the evaluators.
- **The delegation verb list is windowed, not anchored.** Delegation verbs are
  searched in a fixed context window around *any* Exhibit 13 mention, so an
  exhibit-index row sitting beside "as referred to in the notes" can produce
  `refetch_sub_doc`. Tightening it would reclassify already-stored
  documents, so the false-positive surface is preserved deliberately.
- **`line_num` is the anchor's line, not the delegation's**, so the reported line
  can sit outside the quoted reason.
- **No per-family taxonomy lookup here.** Per-family vocabulary reaches consumers
  as `CoverProfile.derived_taxonomy` from `engine/forms/cover/profiles.py`. The
  plugin lookup and the cross-family aggregate do not exist.
