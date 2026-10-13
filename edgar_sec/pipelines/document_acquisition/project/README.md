# project

Layer 4 result projection models for document acquisition.

## Purpose

Defines the streamed terminal result projection used by acquisition review. S6 plan validation and work-order creation remain in `plan_projection/`.

## Contracts

- **Bounded projection**: Target results are spooled to temporary SQLite and exposed through a closeable iterator.
- **Stable identity**: Projection fingerprints are derived from ordered target records.

## Deliberate gaps

- **No S6 plan projection**: This package models S10 result projection; acquisition work-order projection remains separate.
