# Classification fixture store

Stores captured computed products for offline classifier review. It is
mutable local evidence, pinned to one classification plan.

## Purpose

A fixture case is one document's computed products — the normalized
document (text + page analysis), sections/notes, and table geometries —
captured from a live `NormalizationResult` at capture time.

## Contracts

- **Products, not payloads**: replay rebuilds the result from stored
  products and re-runs only what lives above the normalize line
  (context production, form tests, seats, gates, vocabulary); it never
  re-normalizes.
- **Valid exactly for its stamps**: every fixture carries one
  `ProductStamps` set (normalize version, renderer version, page
  policy); a consumer expecting different stamps is refused and the
  fixture regenerates when normalize itself changes.
- **Plan-pinned**: the manifest records the plan pin in the core
  provenance-header vocabulary (plan_format_version, plan_id,
  registry_state, source_snapshot_id) the fixture was captured
  against; a capture under a different pin or stamps is refused.
- **Immutable cases**: a case id already storing different products is
  a conflict, never an overwrite; identical products reuse.
- **Manifest stores provenance only**: identity, storage, timestamps,
  and the details sub-object (store version, plan pin, stamps, case
  count) ride the shared foundation envelope; case digests verify on
  replay.

## Deliberate gaps

- **Grid internals not carried**: span groups, border segments, and
  grid diagnostics are not stored; rows, ascii text, alignments,
  widths, header count, and confidences are the classification-relevant
  products.
- **Cover and reflow not carried**: the cover boundary and reflow
  result are not replay inputs for context production and are rebuilt
  as inert defaults on replay.
