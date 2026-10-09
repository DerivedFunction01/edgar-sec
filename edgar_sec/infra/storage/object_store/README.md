# `edgar_sec/infra/storage/object_store` — Generic SQLite object store

## Purpose

Provides a shared SQLite store for immutable expression nodes and session-scoped movable aliases.

## Contracts

- Object IDs are globally immutable; conflicting payloads are rejected.
- Alias targets must exist as an object or as a cohort in the shared database.
- Session cleanup removes aliases and session pointers but preserves global objects.
- Call `initialize_schema()` before using a new database; cohort schema remains owned by the cohort package.

## Command Surface

<!-- AUTOGEN:COMMANDS:START -->
<!-- AUTOGEN:COMMANDS:END -->

### Usage examples

This library package has no command surface.

## Deliberate Gaps

- Object garbage collection is not automatic; immutable objects remain until a future explicit cleanup operation.
