# `run_state`

## Purpose

This package owns inventory run identity, exclusive locks, and persisted execution
status. It supports resumable coordination without publishing transient state.

## Contracts

- **Pinned identity**: Work orders and manifests are validated before resumed work is accepted.
- **Exclusive ownership**: Stale-lock recovery requires explicit operator confirmation.
- **Read-only discovery**: Status inspection validates persisted artifacts without mutating them.

## Deliberate gaps

- **Lease recovery**: Locks have no lease or automatic owner-liveness detection; stale recovery requires confirmation.
