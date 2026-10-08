# `edgar_sec/infra/storage/object_store` — Generic SQLite object store

## Purpose

Provides a shared SQLite store for immutable expression nodes and session-scoped movable aliases.

## Module Map

| Module | Responsibility |
| :--- | :--- |
| `schema.py` | DDL for sessions, active context, objects, and aliases. |
| `models.py` | Immutable records returned by store operations. |
| `store.py` | Connection hardening, object persistence, session lifecycle, and alias validation. |
| `__init__.py` | Package docstring only; no re-exports. |

## Contracts

- Object IDs are globally immutable; conflicting payloads are rejected.
- Alias targets must exist as an object or as a cohort in the shared database.
- Session cleanup removes aliases and session pointers but preserves global objects.
- Call `initialize_schema()` before using a new database; cohort schema remains owned by the cohort package.

## Public Surface

- `ObjectStore` in [`store.py`](store.py).
- `StoredObject` and `SessionAlias` in [`models.py`](models.py).

## Command Surface

This library package has no command surface.

## Mirrored Tests

- Direct tests live under [`tests/infra/storage/object_store/`](../../../../tests/infra/storage/object_store/).

## Deliberate Gaps

- Object garbage collection is not automatic; immutable objects remain until a future explicit cleanup operation.
