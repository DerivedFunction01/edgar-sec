# run_state

Layer 4 acquisition subpackage for the mutable per-run ledger.

## Purpose

This package stores current target outcomes and append-only acquisition attempts/resolution evidence in a run-scoped SQLite database. It supplies cursor-backed target selection, SQL-derived summaries, and token-owned run locks for later S9 orchestration.

## Contracts

- **Run-scoped database**: The database path binds all target, attempt, and resolution rows to one immutable run identity.
- **Append-only evidence**: Attempts and target-slot resolutions cannot be updated or deleted; target state is the current projection.
- **Bounded access**: Work-order seeds are inserted from an iterable, selected targets use a cursor, and counts are computed in SQL.
- **Lock ownership**: Only a matching owner token can release a lock; remote-host locks are never declared stale from their PID.

## Deliberate gaps

- **No acquisition runner**: This package does not schedule HTTP work, process bodies, or invoke fixture replay.
- **No cleanup authority**: Run-state receipts or processing acknowledgements do not authorize deletion before S11 publication or explicit discard.
