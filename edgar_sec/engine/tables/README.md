# `edgar_sec/engine/tables` — protection, geometry, boundaries, rejection

## Purpose

Handles table rendering, row and boundary detection, false-grid rejection, table-family
classification, and protection of table text during prose rewrites.

## Contracts

- **Table promotion is conservative**: Candidate rows require structural and numeric evidence; ambiguous regions are left unchanged.
- **Rendered geometry accompanies table text**: `TableGeometry` is retained through normalization.
- **Prose-rewriting passes mask tagged tables before changing text**.
- **Masking is idempotent-safe**: A document that already holds a sentinel is not re-masked, and a restore that cannot account for every span raises rather than returning text that silently lost a table.

## Command surface

<!-- AUTOGEN:COMMANDS:START -->
<!-- AUTOGEN:COMMANDS:END -->

## Deliberate gaps

- **No geometry-driven review view.** Geometry is carried through normalization but is not
  rendered as a standalone review artifact.
- **Row-run detection is generic rather than form-specific.** Some financial
  tables are left unwrapped when their row geometry is ambiguous.
- **No per-column financial typing.** Currency and percentage semantics are not inferred.
- **No I/O, no network, no settings reads.** Enforced by the `layer-boundary` scanner: this package
  imports only `foundation`, `domain`, and sibling `engine` modules.
