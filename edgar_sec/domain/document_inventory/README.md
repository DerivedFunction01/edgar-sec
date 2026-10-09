# `edgar_sec.domain.document_inventory`

## Purpose

Own the immutable records shared by document-inventory stages and the durable child-entry schema. This package defines values; cohort readers and parser/worker stages produce them.

## Contracts

- Records are immutable values with no filesystem, network, parser, or stage orchestration behavior.
- `ENTRY_SCHEMA` field order and types are persisted contract; change them only with a schema-version bump.
- Domain imports are restricted to `foundation`.

## Deliberate gaps

- This package does not validate catalog inputs, parse index-page bytes, or manage run/checkpoint artifacts; those operations belong to the pipeline and engine layers.
