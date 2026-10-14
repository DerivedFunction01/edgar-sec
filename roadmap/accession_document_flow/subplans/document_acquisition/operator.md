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

Project selects a fully validated published plan from a paginated list and delegates to
the offline project service. Status and Run select discovered run IDs from paginated
lists; Status also pages through validated work-order target IDs or can show all run
summaries. Missing run roots are reported as empty discovery, not opened as SQLite
databases. Run acquires eligible targets, then processes acquired targets under one run
lock; it confirms live SEC access, defaulting to no, and separately prompts whether to
retry eligible acquisition and processing failures.
The keyed fixture/review console selects an active published plan, creates and fills
plan-pinned fixtures, lists fixtures, generates review artifacts, compares runs, and
analyzes review runs offline. Fill selects a matching run, target, and document-body
attempt from paginated choices and confirms before retaining local evidence; there is
no public replay/export action. Comparison and analysis select validated review runs
through paginated choices. Review generation remains limited to the S9/S10 fixture slice.
Publish returns a gate-blocked result and does not create parts, manifests, or pointers.
The CLI routing and per-target processing are covered by
[`cli.py`](../../../../edgar_sec/pipelines/document_acquisition/cli.py),
[`test_cli.py`](../../../../tests/pipelines/document_acquisition/test_cli.py), and
[`test_run_processing_integration.py`](../../../../tests/pipelines/document_acquisition/test_run_processing_integration.py),
and [`processing/test_worker.py`](../../../../tests/pipelines/document_acquisition/processing/test_worker.py).

## Deferred UX extensions

### Status detail

Run and plan IDs are paginated and filterable. Run-list rows currently show run IDs;
adding validated plan pins, derived state, and aggregate counts remains deferred. A
selected run can page through work-order target IDs and show attempts/outcomes. Improve
inspection of invalid runs so the run-level error remains available without requiring
valid target-work-order discovery. Inspect never mutates a checkpoint or releases staged
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

Create requires a new fixture ID and the active S6 plan. Fill selects a compatible
fixture and a discovered run, then captures every acquired selected staged body from that
run. It does not ask for target, attempt, body-size, or digest input and has no consent
prompt. Listing reports plan pins and run/case counts deterministically without reading
body BLOBs. No user-facing replay/export action exists.

Review generation chooses an active-plan fixture, verifies each selected body, and runs
current acquisition-engine handlers offline. It does not require the associated run's
processing outputs or expose capture/target filters. Comparison selects validated runs
and uses the shared case-level diff. Analysis validates review manifests and per-case
output digests, reports parser outcomes, and does not mutate review or fixture inputs.
Tests are in
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
`document_storage` command surface is retired. The fixture/review console has no snapshot
publishing action.

Tests cover menu transitions, live-network confirmation, EOF/Ctrl-C behavior, and command delegation. M7b runner
and retry/isolation coverage is complete; cleanup remains explicitly gated, because a
receipt or rerun does not authorize deletion. See
  [`test_offline_acceptance.py`](../../../../tests/pipelines/document_acquisition/test_offline_acceptance.py).
