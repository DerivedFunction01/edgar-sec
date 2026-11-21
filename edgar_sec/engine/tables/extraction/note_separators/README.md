# note_separators

## Purpose

Separator evidence and specs for note tables: the credit, deferred tax,
lease, restructuring, stock comp, and tax reconciliation separators that
bound one note's tables against its neighbours in a filing.

## Contracts

- **Separator pairs stay together**: each separator's evidence module reads
  its own specs module in this folder; pairs are never split across folders.
- **Separator evidence composes shared forms**: over `evidence/`'s core-form
  evidence and the family's own separator specs.
- **Deferred tax separation composes the tax reconciliation separator**, its
  measured sibling in this folder, rather than re-deriving its boundary.

## Deliberate gaps

- **Core-statement separators live in `separators/`**: the split is by the
  separated subject (statements vs notes), not by size.
