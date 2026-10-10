# S9 acquisition operator UX

## Purpose and status

This is the interactive flow shared by the S9 command group. The operator dispatches
project, run, and fixture create/capture/list/replay actions to CLI services. Status,
process, review, and snapshot audit remain TODO; publish fails closed on the S11 gate.

## Entry and signatures

```python
from edgar_sec.foundation.runtime.interactive import MenuAction

def build_operator_menu() -> tuple[MenuAction, ...]: ...

def main(argv: list[str] | None = None) -> int: ...
```

`main()` dispatches explicit CLI subcommands; with no command it enters the menu.
The root launcher exposes one `Document Acquisition` entry and does not route through
the legacy `documents`/`document_storage` operator. Project/status/run and fixture menu
actions collect inputs and delegate to the same CLI services; there is no distribution
console.

## Main menu

```text
Document Acquisition
  1. Project a target plan into an acquisition run
  2. Show acquisition run status
  3. Run pending acquisition work
  4. Process acquired targets
  5. Publish a completed run snapshot
  6. Create local fixture
  7. Capture local fixture evidence (confirmation required)
  8. List local fixtures
  9. Replay local fixture (confirmation required)
  10. Review artifact console (build, compare TODOs)
  11. Snapshot status/evidence audit (S11 gate)
  0. Exit
```

Project prompts for a published plan ID and delegates to the offline project service.
Status delegates read-only run inspection. Run is wired to acquisition and separately
confirms live SEC access, defaulting to no; retry selection is a distinct prompt.
Fixture create, capture, list, and replay are wired. Process, review, and snapshot audit
still return TODO results. Publish returns a gate-blocked result and does not create
parts, manifests, or pointers.

## Deferred UX extensions

### Plan selection

List validated plans by ID and summary; after selection, show input digest, catalog
and optional inventory pins, S6 schema versions, and executable/skipped counts.
Projection is offline, so no SEC prompt appears. A reused run is identified as such;
invalid plans return to the menu with no run created.

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

### Process and publish

Process selects acquired targets only and is offline; it does not request another
document. Publish is disabled until every work-order row has a terminal disposition
and every acquired target has a processing result. It previews incomplete/error states
and requires explicit `--allow-errors` consent before publishing such a run. A failed
publication leaves the run resumable and the active snapshot pointer unchanged.

### Deferred distribution console

The common distribution CLI and console are implemented for metadata sync and
inventory. S9's adapter and distribution console are not implemented and are not
registered in the acquisition menu or CLI. SEC rate limits remain host-local under
each machine's configured settings/environment; cross-host coordination and checks
are out of scope and no aggregate limit is implied.

### Fixture actions

Create requires a new fixture ID and refuses an existing ID. Capture requires fixture,
run, target, exact attempt, and a positive byte cap; after collecting them, the operator
requires default-no confirmation before retaining local evidence. Listing is read-only
with optional fixture/capture/target filters and does not select, decompress, or hash
response BLOBs; opening a fixture still validates SQLite integrity. Replay
requires exact fixture/capture/target IDs and a caller-selected output path, then asks a
default-no confirmation before writing. It makes no HTTP request and does not print
document bytes. A metadata-only failure creates no output file.

Replay output is a caller-owned file, not managed S10 staging. There is no durable
replay staging, consumption receipt, or S10 handoff API. Capture refuses exact-form
lazy-index attempts and acquired bundle attempts because complete source/index response
evidence is not retained after a run; supported captures are successful direct bodies
and bodyless failed attempts.

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
`document_storage` pipeline remains a separate command surface. Fixture evidence does
not satisfy the representative S9/S10 evidence and approval required to enable S11
publication.

Tests cover menu transitions, default-no live-network/capture/replay confirmations,
retry confirmation separation, EOF/Ctrl-C behavior, and command delegation.
