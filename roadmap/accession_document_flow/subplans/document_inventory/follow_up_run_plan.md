# Document Inventory: Decoupled Run Lifecycle

## Scope and current state

This plan adds explicit projection, execution, publication, and status operations around
the existing S4/S5 contracts. It changes no parser, worker, snapshot, retention, or
`document_storage` contract.

The current [builder](../../../../edgar_sec/pipelines/document_inventory/snapshot/builder.py)
already performs the complete project → run → publish path. The `inventory build` CLI
and the Snapshot DAG Console's action labeled Publish use that synchronous path; the root
inventory menu does not currently expose a build action. The underlying projection,
coordinator, and writer are separately callable, but there are no lifecycle CLI commands
or a status command yet.

Two current interface mismatches are now resolved: the DAG Console's Publish
action remains the sole surface for SEC requests and still requires a default-no
consent prompt, and the previously ignored `base_snapshot_id` / `--base-snapshot`
override is now enforced. `snapshot.projection.project_catalog_plan()` resolves the
requested base from the selected branch and rejects an explicit base that does not
match the branch tip.

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
- **Resolution in the Decoupled Runner:** `inventory project` selects the base from the
  requested branch (default `main`'s tip) and honors `--base-snapshot-id` for a historical
  base pinned to an explicit branch; `inventory publish` refuses a stale expected tip and
  leaves the pointer unchanged. This matches the shared DAG publication contract.

## Existing lifecycle evidence

| Operation | Existing owner | Persisted contract |
|---|---|---|
| Project | [`snapshot/projection.py`](../../../../edgar_sec/pipelines/document_inventory/snapshot/projection.py) | Atomically creates a validated run directory with `projection_manifest.json`, `run_manifest.json`, cohort relations, and `work_order.parquet`. The base defaults to the requested branch's tip and is pinned to the run; `--base-snapshot-id` pins a historical base only on an explicit branch created at that tip. |
| Run/resume | [`coordinator.py`](../../../../edgar_sec/pipelines/document_inventory/coordinator.py), [`run_lock.py`](../../../../edgar_sec/pipelines/document_inventory/run_lock.py) | Acquires one run lock, validates the run/work-order identity, resumes committed chunks, and optionally retries retryable failures. Chunk attempts and progress journals remain under the transient run directory. |
| Publish | [`snapshot/writer.py`](../../../../edgar_sec/pipelines/document_inventory/snapshot/writer.py) | Validates committed attempts, stages publication, and refuses a stale parent before moving the DAG pointer. |
| Paths | [`paths.py`](../../../../edgar_sec/pipelines/document_inventory/paths.py) | `InventoryRunPaths` resolves runs under the configured transient root; snapshot artifacts are separate. Use these resolvers rather than constructing artifact paths in commands. |
| All-in-one | [`snapshot/builder.py`](../../../../edgar_sec/pipelines/document_inventory/snapshot/builder.py) | Retain `build_inventory()` and `inventory build` for scripted end-to-end use. |

The projection manifest identifies the input plan, pinned base, and work order. S4
manifests and committed-attempt pointers are authoritative for run validation; there is
no independent mutable run-status field. Progress databases are per chunk/attempt, not
one `progress.duckdb` at the run root. S4's `stale_lock_confirmed` flag is an operator
attestation to replace an existing lock; the code does not prove the prior owner is stale.

## Command contracts

Add these explicit CLI operations while retaining `inventory build`:

```text
inventory project --catalog-plan <plan-id> [--base-snapshot-id <id>]
                  [--branch <name>] [--chunk-size <n>]
                  [--explicit-refresh]
inventory run --run-id <run-id> [--workers <n>] [--retry-failures] [--confirm-stale-lock]
inventory publish --run-id <run-id>
inventory status [--run-id <run-id>] [--json]
inventory build --catalog-plan <plan-id> [...]
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
  performs no network work. The run's target branch is advanced under a shared CAS lock;
  a stale `--expected-branch-tip` is refused and the pointer left unchanged, so a stale
  run retried or a new run projected from the new current snapshot.
- **Status** is read-only. It reports the validated projection/run IDs, pinned base,
  work-order size, committed and outstanding chunks, retryable/refusal counts, and lock
  owner metadata. Report an existing lock as present; never label it stale based on age,
  delete it directly, or make status clear it. Replacing a lock requires
  `--confirm-stale-lock`; the menu displays owner metadata and asks default-no, while
  direct CLI use treats the flag as operator attestation that the previous process is
  stopped. This is not an automated stale-lock detector. If ownership cannot be
  verified, cancel.
- A zero-work-order run is not automatically an up-to-date no-op: the projection may
  still contain new accession/source relations. Preserve the builder's no-op and
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

Preserve the current root inventory keys: `1` Query, `d` Distribution, `p` Snapshot DAG,
`f` Fixtures/review, `0` Exit. Add `2` Run lifecycle console rather than replacing Query
or moving existing shortcuts. Its submenu uses `1` Project, `2` Run/resume, `3` Status,
`0` Return. Each action returns to that submenu; it never chains into a network request
or publication automatically. Keep publication in the Snapshot DAG
Console, whose existing publish callback will select a completed run and call the same
`publish` command. `inventory build` remains the explicit all-in-one CLI/script path,
not an additional interactive path that bypasses network consent.

The lifecycle console keeps only session conveniences—selected run ID and selected
catalog plan ID—in memory, displays them in its menu header, and rediscovers artifacts
from their manifests on every selection. A selection from a paginated list can be
cancelled without side effects. After project/run, print the next available action as
guidance; require the operator to select it. Before network work, display the exact
outstanding accession and chunk counts and ask a default-no question. The shared run
command/service takes no consent prompt; consent belongs only to the menu adapter. If a run lock
exists, display its owner metadata and require a default-no attestation that its previous
owner is stopped before using the lock-replacement flag; do not offer a separate
lock-delete action or infer staleness from age/PID data.

## Implementation order and acceptance

1. Add command wrappers that reuse projection, coordinator, and writer APIs; keep
   summaries derived from validated manifests and committed attempts.
2. Add read-only status/discovery using `InventoryRunPaths` and DAG manifests. Validate
   malformed and partial runs by reporting/refusing them, never repairing them in status.
3. Wire the subcommands in `document_inventory/cli.py`; retain the current `build` path.
4. Add the lifecycle console and revise the DAG publish callback to select and publish an
   existing completed run. Preserve root menu keys and use the same command functions
   from the CLI and operator.
5. Add mirrored command/operator tests for cancellation, default-no menu consent, direct
   CLI invocation without an input prompt, resume/retry, stale-lock confirmation,
   incomplete/stale publication refusal, status read-only behavior, and root menu keys.

The work is complete when the targeted mirrored tests, `check.py`, and `check.py --fast`
pass. This lifecycle refactor preserves S5's accession-scoped `scoped_mask` contract and
does not change S0 survey requirements, S8 retention safeguards, or the later S12
vertical integration gate.
