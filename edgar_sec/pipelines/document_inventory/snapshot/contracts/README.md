# `edgar_sec.pipelines.document_inventory.snapshot.contracts`

## Purpose

Own the declarative contracts of the snapshot package: publication and query
error types, immutable snapshot metadata and publication results, the Arrow
schemas for published relations, and the relation specifications built on
them.

## Contracts

- **This group is the package's foundation**: it imports nothing from the
  rest of the package beyond its own modules (specs reads schema).
- **Schema and spec definitions are publication-format definitions**; the
  relation version carried in `schema` gates snapshot compatibility.

## Deliberate gaps

None.
