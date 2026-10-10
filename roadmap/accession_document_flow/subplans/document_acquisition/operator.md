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
  f. Acquisition fixture console
  0. Exit
```

There is no `p` action: S9 has no durable snapshot DAG to publish or query. The
operator retains the selected run ID when entering the fixture console and returns
to the main menu after each completed action. Live distributed work is not exposed in
the first implementation.

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

### Deferred distribution console

The shared distribution lifecycle remains design-only for live SEC work until
cross-host rate coordination is implemented. It is not registered in the initial
operator menu or CLI.

### Fixture console

Offer `capture`, `list`, and `replay`. Capture previews the exact run/attempt targets
and local disk writes, then requires an explicit affirmative confirmation. Listing is
read-only. Replay names the selected fixture/capture/target, makes no HTTP request,
and returns a staged body handle without printing document bytes.

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
