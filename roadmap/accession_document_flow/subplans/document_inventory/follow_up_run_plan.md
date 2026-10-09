# Document Inventory: Decoupled Run Lifecycle

## Scope and current state

This implemented lifecycle separates projection, execution, publication, and status around
the existing S4/S5 contracts. It changes no parser, worker, snapshot, retention, or
`document_storage` contract. Metadata Sync augmentation remains unchanged, Filing Catalog
remains offline, and Inventory gains no augmentation route.

The CLI exposes Project, Run, Status, and Publish; the former combined builder has been
removed without a compatibility shim. Status validates persisted projection outputs and
committed attempts without repairing them. The Snapshot DAG Console selects an existing
completed run and invokes the offline Publish command.

### Analysis: Base Snapshot Override (Now Functional)
- **The override was once a silent mismatch:** `--base-snapshot` / `base_snapshot_id` was
  accepted at the surface but never enforced; a caller requesting a historical base would
  silently anti-join against `current` instead.
- **Architectural guard remains:** `document_inventory` is a cumulative index of observed
  SEC pages, so linear publication still defaults to the tip of the selected branch
  (default `main`) to avoid re-fetching known accessions. Branching off an older snapshot
  is a deliberate operator action: it requires a branch created at that tip first, via
  `inventory dag branch`, and never rewinds or forks `main`.
- **Comparison across pipelines:** `metadata_sync` publishes merge/augment to the selected
  branch (default `main`) with `--expected-branch-tip` for rerun semantics. `filing_catalog`
  materializes to a selected branch under the same CAS guard. `document_inventory` now
  resolves the base from the selected branch and enforces it, unifying the three pipelines'
  branch/CAS contract.
- **Approved lifecycle:** `inventory project` pins the selected branch tip (default
  `main`); an explicit base is accepted only when it is that branch's current tip.
  `inventory publish` selects the target branch and refuses unless its current tip still
  equals the run's pinned base. Alternate-branch runs use that branch for both operations.

## Existing lifecycle evidence

| Operation | Existing owner | Persisted contract |
|---|---|---|
| Project | [`snapshot/projection.py`](../../../../edgar_sec/pipelines/document_inventory/snapshot/projection.py) | Atomically creates a validated run directory with `projection_manifest.json`, `run_manifest.json`, cohort relations, and `work_order.parquet`. The base defaults to the requested branch's tip and is pinned to the run; `--base-snapshot-id` pins a historical base only on an explicit branch created at that tip. |
| Run/resume | [`coordinator.py`](../../../../edgar_sec/pipelines/document_inventory/coordinator.py), [`run_lock.py`](../../../../edgar_sec/pipelines/document_inventory/run_lock.py) | Acquires one run lock, validates the run/work-order identity, resumes committed chunks, and optionally retries retryable failures. Chunk attempts and progress journals remain under the transient run directory. |
| Publish | [`snapshot/writer.py`](../../../../edgar_sec/pipelines/document_inventory/snapshot/writer.py) | Validates committed attempts, stages publication, and refuses a stale parent before moving the DAG pointer. |
| Paths | [`paths.py`](../../../../edgar_sec/pipelines/document_inventory/paths.py) | `InventoryRunPaths` resolves runs under the configured transient root; snapshot artifacts are separate. Use these resolvers rather than constructing artifact paths in commands. |
| Discovery/status | [`run_state.py`](../../../../edgar_sec/pipelines/document_inventory/run_state.py) | Validates persisted projection/run identity and outputs, committed attempts, failure/refusal outcomes, cancellation, lock ownership, and matching published snapshots without modifying run state. |
| Command services | [`commands/`](../../../../edgar_sec/pipelines/document_inventory/commands/README.md) | Separates the offline Project, explicit network Run, read-only Status, and offline Publish commands. |

The projection manifest identifies the input plan, pinned base, and work order. S4
manifests and committed-attempt pointers are authoritative for run validation; status is
derived from those artifacts. A small cancellation marker preserves the S4 cancellation
barrier across process exit. Progress databases are per chunk/attempt, not one
`progress.duckdb` at the run root. S4's `stale_lock_confirmed` flag is an operator
attestation to replace an existing lock; the code does not prove the prior owner is stale.

## Command contracts

The approved public lifecycle commands are:

```text
inventory project --catalog-plan <plan-id> [--base-snapshot-id <id>]
                  [--branch <name>] [--chunk-size <n>]
                  [--explicit-refresh]
inventory run --run-id <run-id> [--workers <n>] [--retry-failures] [--confirm-stale-lock]
inventory publish --run-id <run-id> [--branch <name>]
inventory status [--run-id <run-id>] [--json]
```

- **Project** is offline. It resolves the base from the requested branch (default `main`),
  pins it into the run intent and S4 identity, and accepts `--base-snapshot-id` only on a
  branch created at that base. It reports the run ID, source plan, base snapshot, branch,
  accession/work-order counts, and chunk size. Publication compares against the pinned
  base and refuses stale lineage; the operator projects a new run from the new current
  snapshot rather than rebasing.
- **Run** validates the existing run directory and calls the S4 coordinator. Invoking
  `inventory run` directly is explicit network intent and does not prompt; with non-
  interactive CLI use, the command itself is consent. The menu operator must show
  outstanding accession/chunk counts and ask a default-no confirmation before invoking
  the same run command. Resume uses the same run identity; `--retry-failures` affects
  retryable outcomes only. Replacing an existing lock separately requires
  `--confirm-stale-lock` and an operator attestation.
- **Publish** validates the run through S5 and reports the published snapshot ID. It
  performs no network work. The selected target branch (default `main`) must still point
  at the run's pinned base; otherwise publication is refused and the pointer left
  unchanged. An alternate branch is selected at both Project and Publish, not persisted
  as part of run identity.
- **Status** is read-only. It reports the validated projection/run IDs, pinned base,
  work-order size, pending accessions, committed and outstanding chunks, retryable/refusal counts, and lock
  owner metadata. Report an existing lock as present; never label it stale based on age,
  delete it directly, or make status clear it. Replacing a lock requires
  `--confirm-stale-lock`; the menu displays owner metadata and asks default-no, while
  direct CLI use treats the flag as operator attestation that the previous process is
  stopped. This is not an automated stale-lock detector. If ownership cannot be
  verified, cancel.
- A zero-work-order run is not automatically an up-to-date no-op: the projection may
  still contain new accession/source relations. Preserve the writer's no-op and
  publication decisions rather than inferring them from the missing-accession count.
- Report `published_snapshot_id` only when an inventory snapshot manifest's
  `run_intent_id` matches the run ID. Do not infer `published` from missing transient
  files or a completed chunk count.

## Operator interaction

Use the shared terminal primitives in
[`foundation/runtime/interactive.py`](../../../../edgar_sec/foundation/runtime/interactive.py):
`build_menu`, `prompt_paginated_choice`, `prompt_text`, and `operator_entrypoint`. Keep
selection/cancellation and command behavior in the same style as the
[filing-catalog operator](../../../../edgar_sec/pipelines/filing_catalog/operator.py)
and [metadata-sync operator](../../../../edgar_sec/pipelines/metadata_sync/operator.py).

Preserve root keys `1` Query, `d` Distribution, `p` Snapshot DAG,
`f` Fixtures/review, and `0` Exit. Add top-level `2` Project, `3` Status, and `4` Run;
do not add a lifecycle submenu or change Metadata Sync or Filing Catalog operators.
The Snapshot DAG Publish action selects an existing run and invokes Publish; it never
calls the S4 coordinator. Before interactive network work, display pending accession
and chunk counts and require default-no confirmation. Direct `inventory run` CLI use
does not prompt. Lock replacement remains a separate explicit attestation.

## Implementation and acceptance

The lifecycle split is implemented. Mirrored tests cover command routing, default-no
interactive consent, persisted cancellation, resume/retry through the S4 tests, stale-lock
confirmation, partial/failed/stale publication refusal, run discovery, and read-only status.
S5's accession-scoped `scoped_mask` contract is unchanged; S0 survey requirements, S8
retention safeguards, and the later S12 vertical integration gate remain separate.
