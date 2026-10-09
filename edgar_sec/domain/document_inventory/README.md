# `edgar_sec.domain.document_inventory`

## Purpose

Own the immutable records shared by document-inventory stages and the durable child-entry schema. This package defines values; cohort readers and parser/worker stages produce them.

## Contracts

- **Immutability**: Records are immutable values with no filesystem, network, parser, or stage orchestration behavior.
- **Arrow schema stability**: `ENTRY_SCHEMA` field order and types are persisted contract; change them only with a schema-version bump.
- **Zero I/O**: Domain imports are restricted to `foundation`.

## Deliberate gaps

- **No catalog validation or parsing**: Catalog input validation, index-page parsing, and artifact management belong to pipeline and engine layers.
