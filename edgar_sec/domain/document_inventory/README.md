# `edgar_sec.domain.document_inventory`

## Purpose

Own the immutable records shared by document-inventory stages and the durable child-entry schema. This package defines values; cohort readers and parser/worker stages produce them.

## Layout

| Module | Responsibility |
| :--- | :--- |
| `models.py` | Cohort projection records, index-page parse contracts, and inventory-entry identity. |
| `schemas.py` | Versioned Arrow schema for durable inventory entries. |

## Contracts

- Records are immutable values with no filesystem, network, parser, or stage orchestration behavior.
- `ENTRY_SCHEMA` field order and types are persisted contract; change them only with a schema-version bump.
- Domain imports are restricted to `foundation`.

## Public surface

Import records from [`models.py`](models.py) and the durable entry schema from [`schemas.py`](schemas.py). There is no command surface.

## Tests

Mirrored tests: `tests/domain/document_inventory/`.

## Deliberate gaps

- This package does not validate catalog inputs, parse index-page bytes, or manage run/checkpoint artifacts; those operations belong to the pipeline and engine layers.
