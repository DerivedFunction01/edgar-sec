# distribution

Layer 2 package for partitioning pipeline work into transferable worker bundles.

## Purpose

The package owns assignment, bundle, receipt, menu, and CLI mechanics shared by
pipelines. Pipeline adapters own work discovery, execution, and validation before
coordinator adoption.

## Contracts

- **Opaque identity**: The shared protocol carries `work_id`; adapters interpret it
  as a pipeline plan, run, or another immutable execution unit.
- **Immutable assignment**: A worker assignment binds its pipeline, work digest,
  worker identity, and chunk indexes.
- **Receipt evidence**: Receipts bind completed assigned chunks and each output's
  relative path, byte size, and SHA-256 digest; adapters validate pipeline-specific
  outcomes and schemas.
- **Affinity and refusal**: Shared import rejects mismatched pipeline, work,
  assignment, worker, or chunk identity before adapter adoption.
- **Idempotent adoption**: Adapters report newly adopted and already present chunks
  separately and refuse conflicting content.
- **Per-host pacing**: Each worker uses its configured SEC client policy; no
  cross-host aggregate limit is provided.

## Deliberate gaps

- **No transport mechanism**: Bundles are files; operators transfer them between
  machines and run the generated commands.
- **No cluster scheduler**: Partition assignment is deterministic, but worker
  placement and execution are operator-controlled.
- **No aggregate rate coordinator**: Independent machine rate limiters do not
  establish a shared SEC request budget.
