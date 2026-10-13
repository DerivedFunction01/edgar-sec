# S9 acquisition operator UX

## Purpose and status

This is the interactive flow shared by the S9 command group. Project, status, combined
run/process, plan-pinned fixture create/fill/list, and review generate/compare/analyze
dispatch to CLI services. Review is implemented only for the limited S9/S10 fixture
slice. A run processes acquired targets under the acquisition run lock. Wiring is
covered by
[`operator.py`](../../../../edgar_sec/pipelines/document_acquisition/operator.py),
[`test_operator.py`](../../../../tests/pipelines/document_acquisition/test_operator.py),
[`test_review.py`](../../../../tests/pipelines/document_acquisition/commands/test_review.py),
and [`review_artifacts/test_adapter.py`](../../../../tests/pipelines/document_acquisition/review_artifacts/test_adapter.py).

## Entry and signatures

```python
from edgar_sec.foundation.runtime.interactive import MenuAction

def build_operator_menu() -> tuple[MenuAction, ...]: ...

def main(argv: list[str] | None = None) -> int: ...
```

`main()` dispatches explicit CLI subcommands; with no command it enters the menu.
The root launcher exposes one `Document Acquisition` entry and does not route through
the legacy `documents`/`document_storage` operator. Numbered lifecycle actions use the
root menu; snapshot and fixture/review actions use keyed consoles. Acquisition has no
distribution adapter or full snapshot DAG console.

## Main menu

```text
Document Acquisition
  1. Project a target plan into an acquisition run
  2. Inspect acquisition runs
  3. Run acquisition and process acquired targets (live SEC; confirmation required)
  p. Snapshot console (publish, status; S11 gate)
  f. Fixtures and review console (create, fill, list, generate, compare, analyze)
  0. Exit
```

Project prompts for a published plan ID and delegates to the offline project service.
Status delegates read-only run inspection. Run acquires eligible targets, then processes
acquired targets under one run lock; it confirms live SEC access, defaulting to no, and
separately prompts whether to retry eligible acquisition and processing failures.
The keyed fixture/review console selects an active published plan, creates and fills
plan-pinned fixtures, lists fixtures, generates review artifacts, compares runs, and
analyzes review runs offline. Fixture fill confirms before retaining local evidence;
there is no public replay/export action. Review generation remains limited to the
S9/S10 fixture slice.
Publish returns a gate-blocked result and does not create parts, manifests, or pointers.
The CLI routing and per-target processing are covered by
[`cli.py`](../../../../edgar_sec/pipelines/document_acquisition/cli.py),
[`test_cli.py`](../../../../tests/pipelines/document_acquisition/test_cli.py), and
[`test_run_processing_integration.py`](../../../../tests/pipelines/document_acquisition/test_run_processing_integration.py),
and [`processing/test_worker.py`](../../../../tests/pipelines/document_acquisition/processing/test_worker.py).

## Deferred UX extensions

### Active S6 plan

The fixture/review console lists fully validated published S6 plans by stable ID, target
row count, and digest. Plan selection is session-local and switchable. Fixture creation
uses the active plan pin; switching plans never changes existing fixtures.

### Status detail

List valid and invalid runs with their plan IDs, derived state, and aggregate counts.
Selecting a valid run shows attempts and target outcomes; invalid runs show the error
code without a repair action. Inspect never mutates a checkpoint or releases staged
bodies.

### Run preview

Show the chosen run's pending count, retryable failures, and assigned/in-flight work
before starting. Ask a distinct live-network confirmation, defaulting to no. If
retryable failures exist, ask separately whether to retry them; no response preserves
them without retry. `Ctrl-C` stops scheduling, commits already completed outcomes,
and leaves remaining work resumable. A noninteractive CLI run is an explicit network
action; no confirmation flag is required.

### Run and publish

Run uses network access only for eligible acquisition work; processing is performed
offline for acquired targets before the run lock is released. The run report includes
both acquisition and processing results. Publish is disabled until every work-order row has a terminal disposition
and every acquired target has a processing result. It previews incomplete/error states
and requires explicit `--allow-errors` consent before publishing such a run. A failed
publication leaves the run resumable and the active snapshot pointer unchanged.

### Deferred distribution console

The common distribution CLI and console are implemented for metadata sync and
inventory. S9's adapter and distribution console are not implemented and are not
registered in the acquisition menu or CLI. SEC rate limits remain host-local under
each machine's configured settings/environment; cross-host coordination and checks
are out of scope and no aggregate limit is implied.

### Fixture and review actions

Create requires a new fixture ID and the active S6 plan. Fill is available only for a
fixture pinned to that active plan and requires exact run, target, and retained attempt
IDs plus a positive byte cap. It shows these values before a default-no consent prompt;
declining performs no append. Listing reports plan pins, capture/case counts, and
acquisition statuses in deterministic order without reading response BLOBs. No
user-facing replay/export action exists.

Review generation chooses an active-plan fixture and optional capture/target filters. It
verifies the selected fixture body in temporary storage, validates its associated S9 run
and pinned work order, then reviews the staged run body through operation pins.
Comparison selects validated runs and uses the shared case-level diff. Analysis
validates review manifests and per-case output digests, reports fixture-verification
and operation outcomes, and does not mutate review or fixture inputs. Review actions are
offline with no confirmation checkpoint. Tests are in
[`test_operator.py`](../../../../tests/pipelines/document_acquisition/test_operator.py),
[`fixture_store/test_capture.py`](../../../../tests/pipelines/document_acquisition/fixture_store/test_capture.py),
and [`review_artifacts/test_analyzer.py`](../../../../tests/pipelines/document_acquisition/review_artifacts/test_analyzer.py).

### Snapshot console

List branches/tags and query a named immutable snapshot without network access. Payload
reads verify the uncompressed-byte digest and size after Parquet decoding; metadata
queries do not materialize payload columns.

### Exit, EOF, and cancellation

`0` or EOF exits cleanly. Cancelling a selection or answering no performs no network
request and returns to the nearest menu. Input validation errors remain local to the
current action; they do not discard a previously selected run context.

## Output and tests

Fixture CLI `--json` output is stable and sorted. Command errors use the CLI's typed
error formatting and exit-code mapping in both entry modes. The legacy
`document_storage` command surface is retired. Fixture evidence does not satisfy the
representative S9/S10 evidence and approval required to enable S11 publication.

Tests cover menu transitions, default-no live-network/fill confirmations,
retry confirmation separation, EOF/Ctrl-C behavior, and command delegation. M7b runner
and retry/isolation coverage is complete; cleanup remains explicitly gated, because a
receipt or rerun does not authorize deletion. See
[`test_offline_acceptance.py`](../../../../tests/pipelines/document_acquisition/test_offline_acceptance.py).
