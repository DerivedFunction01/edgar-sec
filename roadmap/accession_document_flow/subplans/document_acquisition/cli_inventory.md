# S9 — Document Acquisition CLI Inventory

## Purpose and status

This is the index for replacing the legacy document-storage surface with command-
oriented acquisition, processing, and publication contracts. It records tracked CLI
patterns and the proposed operator surface; linked documents specify each command's
behavior and the integrated [lifecycle plan](lifecycle.md).

Shared package boundaries and cross-command prerequisites are in
[the S9 architecture](architecture.md); command contracts must use its schema, path,
and settings owners rather than duplicate them. The staged implementation sequence
and safe parallel workstreams are in the [S9 implementation plan](plan.md).

The dedicated `acquisition` launcher and command/operator are registered. The offline
`project` command is implemented; status/run/process/fixture/review/snapshot tracks
return explicit TODO results, and publish returns a gate-blocked result. No command
fetches, processes, or publishes data. The `documents` launcher still invokes the
legacy `document_storage` CLI and remains separate.

## Tracked CLI patterns

### Root launcher

[`run.py`](../../../../run.py) has separate entries for acquisition and legacy
document storage. The legacy entry is
`Document Storage — Document acquisition, normalization, snapshots, and review
(removed soon)`, routed to `document_storage.cli`. The dedicated **Document
Acquisition** entry exposes separate project, acquire, process, publish, fixture,
review, and snapshot tracks. S9, S10, and S11 remain distinct owners under the shared
command group.

### Document Inventory

[`document_inventory/operator.py`](../../../../edgar_sec/pipelines/document_inventory/operator.py)
uses four numbered actions and three keyed consoles. Its implemented menu is:

```text
Document Inventory
  1. Query document inventory
  2. Project a published plan into an inventory run
  3. Show inventory run status
  4. Run pending inventory work
  d. Worker distribution console (shared distribution; host-local SEC settings)
  p. Snapshot DAG console (publish, switch current, inspect, branches, tags)
  f. Fixtures and review console (create, fill, list, generate, compare)
  0. Exit
```

The matching CLI in
[`document_inventory/cli.py`](../../../../edgar_sec/pipelines/document_inventory/cli.py)
exposes `project`, `run`, `status`, `publish`, and `query`, plus shared DAG,
distribution, and review/fixture commands. `run` is the network operation; the
interactive operator explicitly confirms it and separately asks whether to retry
previous failures. Publishing is a real inventory snapshot lifecycle, not just a
run-completion action.

### Metadata Sync

[`metadata_sync/operator.py`](../../../../edgar_sec/pipelines/metadata_sync/operator.py)
uses the same run-oriented shape with state carried between choices:

```text
Metadata Sync (Phase 01)
  1. Plan generation
  2. Status and resume inspect
  3. Run chunks
  4. Augment published snapshot
  d. Worker distribution console (export, worker, import, commands)
  p. Snapshot DAG console (merge/publish, switch current, inspect, branches, tags)
  0. Exit
```

Its CLI in [`metadata_sync/cli.py`](../../../../edgar_sec/pipelines/metadata_sync/cli.py)
provides `plan`, `status`, `run`, `merge`, `augment`, `distrib`, and `dag`. The
operator delegates to the same command functions, retains selected run context, and
prompts before SEC network work. `merge` publishes snapshots, so that action is
specific to a pipeline with a published durable output.

### Legacy Document Storage

[`document_storage/cli.py`](../../../../edgar_sec/pipelines/document_storage/cli.py)
currently presents a five-choice fixture lifecycle when launched without arguments:
fill/extend a fixture, run from a fixture, list fixtures, build review artifacts,
and compare review runs. Its `documents` command group is not a model for S9's
target-plan run lifecycle: S9 is designed to consume S6 plans and explicitly keeps
fixture bodies as replay evidence rather than publishing a durable payload store.

## Registered S9 launcher and operator shape

Keep a separate root entry for target-plan acquisition, processing, and publication;
the `acquisition` entry is registered, while legacy `documents` remains isolated:

```text
  Document Acquisition - Acquire eligible targets from S6 plans and inspect resumable runs
```

The registered operator menu is run-oriented, modeled on inventory's
project/status/run choices. Its actions are placeholders; unlike the CLI, project is
not yet wired into the interactive selection flow:

```text
Document Acquisition
  1. Project a target plan into an acquisition run
  2. Show acquisition run status
  3. Run pending acquisition work
  4. Process acquired targets
  5. Publish a completed run snapshot
  f. Acquisition fixtures console (capture, list, replay TODOs)
  r. Review artifacts console (build/compare TODOs)
  p. Snapshot status/evidence audit (S11 gate)
  0. Exit
```

The acquisition operator does not register a distribution console because its
pipeline-specific adapter is not implemented. The shared, pipeline-neutral
distribution infrastructure is already used by metadata sync and inventory. Inventory
work selection includes only valid existing runs, and resolving a distribution work ID
does not project a catalog plan; projection is an explicit inventory operation.
Snapshot publication is separate from acquisition run completion and requires S10
results plus the publisher's integrity checks.

The local command-line counterpart defines project, status, run, process, publish,
snapshot status/audit, and acquisition-specific fixture/review command shapes with
stable run/plan/snapshot IDs. `project` creates or reuses an offline transient run;
status/run/process/fixture/review/snapshot remain fail-closed TODO tracks, and
publication reports its evidence-and-approval gate. Future network execution is an
explicit CLI action; the interactive operator must separately confirm it, defaulting
to no, and expose retry selection rather than silently retrying failed requests.
`acquisition distrib` remains planned and unimplemented. The common CLI uses
`--work-id`, and its interactive console retains selected work for the session. SEC
rate limiting uses each host's configured settings/environment; cross-host
coordination and checks are out of scope, so no cluster-wide limit is implied.

## Follow-up documents

Use the [architecture](architecture.md) as the cross-command prerequisite, then
follow the command contracts below, each focused on a user-visible option and its
behavior:

- [Project an acquisition run](project.md): validate a self-contained S6 target
  plan, derive stable run identity, and persist eligible work.
- [Inspect acquisition status](status.md): report validated run state, pending work,
  terminal outcomes, retryable failures, and interruption state.
- [Run and retry acquisition](run/index.md): define network execution, exact bundle
  selection, bounded transfer, cancellation, and result recording.
- [Distribute acquisition work](distribution/index.md): define export, remote
  execution, receipt verification, discovery, and coordinator adoption.
- [Capture and replay fixtures](fixtures/index.md): define explicit capture, fixture
  discovery, integrity checks, and zero-network replay.
- [Operator UX](operator.md): define menu transitions, explicit network confirmation,
  context retention, cancellation, and common CLI/operator dispatch.
- [Shared schemas](schemas.md), [paths](paths.md), and
  [settings](settings.md): define the S6 input contract, versioned S9 run/handoff
  records, managed artifact paths, and finite resource/network settings.
- [Architecture](architecture.md): set the package/layer boundary and order the
  shared contracts before command implementation.
- [Implementation plan](plan.md): assess readiness, assign independent lower-layer
  and pipeline workstreams, and gate runner integration on their contracts.
- [End-to-end lifecycle and publication](lifecycle.md): define S9/S10 transient state,
  worker bundles, S11 binary/text Parquet relations, cleanup rules, and legacy differences.

The existing [S9 design](../S9_acquisition.md) and S9a–S9d documents are earlier
design material, not proof of runtime implementation. The registered menu is a
placeholder only; do not infer that any acquisition, processing, fixture, or
publication service is implemented from its command shape.
