# S9 — Document Acquisition CLI Inventory

## Purpose and status

This is the index for the current command-oriented acquisition, processing, and publication contracts.
It records tracked CLI patterns and the operator surface; linked documents specify
each command's behavior and the integrated [lifecycle plan](lifecycle.md).

Shared package boundaries and cross-command prerequisites are in
[the S9 architecture](architecture.md); command contracts must use its schema, path,
and settings owners rather than duplicate them. The staged implementation sequence
and safe parallel workstreams are in the [S9 implementation plan](plan.md).

The dedicated `acquisition` launcher and command/operator are registered. Project,
status, combined run/process, and plan-pinned fixture/review actions are wired. Review
generation, comparison, and offline analysis cover the limited S9/S10 fixture slice. The
former `documents` launcher and `document_storage`
runtime package are retired. Command and fixture wiring are covered by
[`cli.py`](../../../../edgar_sec/pipelines/document_acquisition/cli.py),
[`test_cli.py`](../../../../tests/pipelines/document_acquisition/test_cli.py), and
[`test_fixture.py`](../../../../tests/pipelines/document_acquisition/commands/test_fixture.py);
the per-target processing boundary is covered by
[`processing/worker.py`](../../../../edgar_sec/pipelines/document_acquisition/processing/worker.py)
and [`processing/test_worker.py`](../../../../tests/pipelines/document_acquisition/processing/test_worker.py).

## Tracked CLI patterns

### Root launcher

[`run.py`](../../../../run.py) registers the **Document Acquisition** entry with
project, combined run/process, publish, fixture, review, and snapshot tracks.
S9, S10, and S11 remain distinct owners under the shared command group. The former
`Document Storage` entry was removed with its runtime package.

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

### Historical Document Storage Surface

The former `documents` command exposed a fixture lifecycle for the retired
`document_storage` pipeline. Its behavior is retained as historical evidence in the
[legacy processing trace](../S10_legacy_processing_trace.md), not as a live command or
runtime dependency. S9 consumes S6 plans and keeps fixture bodies as replay evidence
rather than publishing a durable payload store.

## Registered S9 launcher and operator shape

Keep the root entry for target-plan acquisition, processing, and publication; the
legacy `documents` entry is retired:

```text
  Document Acquisition - Acquire eligible targets from S6 plans and inspect resumable runs
```

The registered operator uses numbered lifecycle actions and keyed snapshot and
fixture/review consoles. Project/status/run and fixture actions dispatch to their CLI
services. Run processes acquired targets under the same run lock; fixture actions are
plan-pinned and review generation/comparison/analysis are offline. See
[`operator.py`](../../../../edgar_sec/pipelines/document_acquisition/operator.py),
[`test_operator.py`](../../../../tests/pipelines/document_acquisition/test_operator.py),
[`test_review.py`](../../../../tests/pipelines/document_acquisition/commands/test_review.py),
and [`review_artifacts/test_adapter.py`](../../../../tests/pipelines/document_acquisition/review_artifacts/test_adapter.py):

```text
Document Acquisition
  1. Project a target plan into an acquisition run
  2. Show acquisition run status
  3. Run acquisition and process acquired targets (live SEC; confirmation required)
  p. Snapshot console (publish, status; S11 gate)
  f. Fixtures and review console (create, fill, list, generate, compare, analyze)
  0. Exit
```

The snapshot console groups publish and status; the fixture/review console owns local
fixture evidence and review analysis. Acquisition does not register inventory's
distribution or full DAG operations: its distribution adapter is not implemented.

The local command-line counterpart defines project, status, combined run, publish,
snapshot status/audit, and acquisition-specific fixture/review commands. `project`
creates or reuses an offline transient run. Fixture creation pins the active published
plan; fill validates that pin and fetches selected parser inputs from the plan without
creating or requiring an S9 run. Exact-form catalog-direct targets may fetch and cache
their accession index once per fixture when no inventory entry is pinned. List reports
deterministic capture/case/lazy-index summaries. Review generation parses the fixture
bytes with current acquisition-engine handlers; compare and offline analyze consume those
parser artifacts. Schema v3 rejects older fixture-store formats without migration. Both
the interactive operator and CLI require explicit live-network authorization for fill.
CLI network
execution is explicit and exposes retry selection rather than silently retrying failed
requests.
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
- [Capture and review fixtures](fixtures/index.md): define S6-pinned fixture capture,
  deterministic discovery, integrity checks, retained-evidence limits, and offline review.
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
- [Combined acquisition run follow-up](combined_run_follow_up.md): merge target fetch and
  processing into one resumable CLI/operator action and remove the separate `process` entry.
- [Fixture and review console follow-up](fixture_review_console_follow_up.md): align local
  fixture and review interactions with Inventory while retaining acquisition-specific
  capture and fixture-body verification.

The existing [S9 design](../S9_acquisition.md) and S9a–S9d documents include earlier
design material; consult the status records at their tops for current implementation
state. The legacy `documents` command and `document_storage` runtime are retired.
Fixture evidence is not an S11 payload store, and S11 publication still requires its
evidence and approval gate. Run-level processing is available, but it does not make
unbudgeted normalization production-ready. M7b lifecycle coverage is complete, but
body cleanup remains explicitly gated; see
[`test_offline_acceptance.py`](../../../../tests/pipelines/document_acquisition/test_offline_acceptance.py)
and [`processing/test_worker.py`](../../../../tests/pipelines/document_acquisition/processing/test_worker.py).
