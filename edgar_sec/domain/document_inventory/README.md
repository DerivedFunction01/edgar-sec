# `edgar_sec.domain.document_inventory`

## Purpose

Own the immutable records shared by document-inventory stages and the durable child-entry schema. This package defines values; cohort readers and parser/worker stages produce them.

## Contracts

- **Immutability**: Records are immutable values with no filesystem, network, parser, or stage orchestration behavior.
- **Arrow schema stability**: `ENTRY_SCHEMA` field order and types are persisted contract; change them only with a schema-version bump.
- **Zero I/O**: Domain imports are restricted to `foundation`.
- **Canonical projection**: The published entry is the identity the client layers project from: the canonical attachment row carries `entry_id`, `table_kind`, nullable sequence, document type, description, filename, href/archive URL, and byte size from the entry, and both client loaders hydrate attachment objects from that one row shape.
- **Honest absence**: A field the enumerating vehicle never observed stays `None` in the entry and in every projection of it; no downstream layer fabricates a value for it.

## Deliberate gaps

- **No catalog validation or parsing**: Catalog input validation, index-page parsing, and artifact management belong to pipeline and engine layers.
- **No acquisition identity**: The entry carries no payload sha or acquisition state; payload presence is an acquisition-relation fact the client joins against the entry's filing, not an inventory field.
