# S9 acquisition operator UX

## Purpose and status

This is the interactive flow shared by the S9 command group. It is design-only and
modeled on the run-oriented `document_inventory` and `metadata_sync` operators. The
operator delegates to the same command services used by `acquisition` CLI calls.

## Entry and signatures

```python
import argparse
from collections.abc import Callable, Sequence

def build_parser() -> argparse.ArgumentParser: ...

def run_acquisition_operator(
    *,
    paths: AcquisitionPaths,
    read_line: Callable[[str], str],
    write_line: Callable[[str], None],
) -> int: ...

def main(argv: Sequence[str] | None = None) -> int: ...
```

`main()` dispatches explicit CLI subcommands; with no command it enters the menu.
The root launcher exposes one `Document Acquisition` entry and does not route through
the legacy `documents`/`document_storage` operator. The operator does not have its
own plan, status, run, distribution, or fixture implementation.

## Main menu

```text
Document Acquisition
  1. Project a target plan into an acquisition run
  2. Show acquisition run status
  3. Run pending acquisition work
  4. Process acquired targets
  5. Publish a completed run snapshot
  f. Acquisition fixture console
  p. Acquisition snapshot console
  0. Exit
```

Project, Status, Run, Process, and Publish delegate to their command services. Publish
is separate from Run completion and previews target/error counts, the parent branch
tip, and payload bytes to adopt. The `p` console delegates read-only snapshot queries
and shared DAG branch/tag operations; it does not mutate snapshot contents. The
operator retains selected run/snapshot IDs when entering a sub-console. Live
distributed work is not exposed in the first implementation.

## User flows

### Project

List validated plans by ID and summary; after selection, show input digest, catalog
and optional inventory pins, S6 schema versions, and executable/skipped counts.
Projection is offline, so no SEC prompt appears. A reused run is identified as such;
invalid plans return to the menu with no run created.

### Status

List valid and invalid runs with their plan IDs, derived state, and aggregate counts.
Selecting a valid run shows attempts and target outcomes; invalid runs show the error
code without a repair action. Inspect never mutates a checkpoint or releases staged
bodies.

### Run

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

### Fixture console

Offer `capture`, `list`, and `replay`. Capture previews the exact run/attempt targets
and local disk writes, then requires an explicit affirmative confirmation. Listing is
read-only. Replay names the selected fixture/capture/target, makes no HTTP request,
and returns a staged body handle without printing document bytes.

### Snapshot console

List branches/tags and query a named immutable snapshot without network access. Payload
reads verify the uncompressed-byte digest and size after Parquet decoding; metadata
queries do not materialize payload columns.

### Exit, EOF, and cancellation

`0` or EOF exits cleanly. Cancelling a selection or answering no performs no network
request and returns to the nearest menu. Input validation errors remain local to the
current action; they do not discard a previously selected run context.

## Output and tests

Menu summaries and CLI text use the same report models. `--json` prints stable,
sorted JSON without paths outside the resolved project root or secret settings.
Command errors use the same typed errors and exit-code mapping in both entry modes.

Tests cover each menu transition, retained run context, default-no confirmation,
retry confirmation separation, EOF/Ctrl-C behavior, command delegation, and proof
that cancelled actions make zero SEC requests.
