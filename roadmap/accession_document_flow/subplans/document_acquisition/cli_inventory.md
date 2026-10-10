# S9 — Document Acquisition CLI Inventory

## Purpose and status

This is the index for replacing the S9 acquisition subplans with command-oriented
contracts. It records tracked CLI patterns and the proposed operator surface; linked
documents specify each command's behavior. It does not specify S10 normalization or
the later durable payload store.

Shared package boundaries and cross-command prerequisites are in
[the S9 architecture](architecture.md); command contracts must use its schema, path,
and settings owners rather than duplicate them. The staged implementation sequence
and safe parallel workstreams are in the [S9 implementation plan](plan.md).

S9 acquisition is design-only. The current `documents` launcher still invokes the
legacy `document_storage` fixture operator; it is marked for removal and is not the
replacement S9 CLI.

## Tracked CLI patterns

### Root launcher

[`run.py`](../../../../run.py) currently has eight entries. The relevant entry is
`Document Storage — Document acquisition, normalization, snapshots, and review
(removed soon)`, routed to `document_storage.cli`. The future S9 entry should be
named **Document Acquisition** and describe only the acquisition work it owns; S10
processing and later durable storage/publication are separate stages.

### Document Inventory

[`document_inventory/operator.py`](../../../../edgar_sec/pipelines/document_inventory/operator.py)
uses four numbered actions and three keyed consoles. Its implemented menu is:

```text
Document Inventory
  1. Query document inventory
  2. Project a published plan into an inventory run
  3. Show inventory run status
  4. Run pending inventory work
  d. Worker distribution console (design only; live remote SEC work deferred)
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

## Proposed S9 launcher and operator shape

Replace the legacy root entry with a separate entry for target-plan acquisition:

```text
  Document Acquisition - Acquire eligible targets from S6 plans and inspect resumable runs
```

The dedicated operator should be small and run-oriented, modeled on inventory's
project/status/run choices:

```text
Document Acquisition
  1. Project a target plan into an acquisition run
  2. Show acquisition run status
  3. Run pending acquisition work
  f. Acquisition fixtures console (capture, list, replay)
  0. Exit
```

The initial local implementation does not register the distribution console. Its
design remains available below, but live remote SEC work is gated on cross-host rate
coordination.

The local command-line counterpart should support project, status, run, and
acquisition-specific fixture commands with stable run/plan IDs. Network execution is
an explicit CLI action; the interactive operator must separately confirm it,
defaulting to no, and expose retry selection rather than silently retrying failed
requests. `acquisition distrib` remains design-only for live SEC work until a
cross-host rate policy is selected and enforced; the local broker's rate setting is
not a cluster-wide limit.

This shape deliberately omits `query`, `publish`/`merge`, and a snapshot DAG console:
S9 consumes an immutable S6 target plan, records resumable run results and fixture
evidence, and does not own a durable document snapshot. Add a published-artifact or
query surface only when a later stage owns that artifact.

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

The existing [S9 design](../S9_acquisition.md) and S9a–S9d documents are earlier
design material, not proof of implementation. These command contracts supersede
their decomposition as they are reviewed; do not infer that the proposed menu is
implemented.
