# `acquisition run`

## Purpose and status

Execute pending target work from a validated S9 run and resume it safely after
interruption. This command is design-only; the replacement S9 acquisition runner is
not implemented.

## UX and service signature

The operator selects a projected run, previews pending/assigned/retryable targets,
then explicitly confirms live SEC access (default no). Retryable failures are a
separate choice; non-retryable, acquired, skipped, ambiguous, `not_filed`, and
`required_missing` targets are not retried. The CLI invocation itself authorizes
network access and accepts `--retry-failures` explicitly. No work produces a
successful no-op summary without
constructing a network client.

```python
from collections.abc import Callable
from datetime import datetime

def execute_acquisition_run(
    run_id: str,
    *,
    retry_failures: bool,
    paths: AcquisitionPaths,
    policy: AcquisitionPolicy,
    transport: AcquisitionTransport,
    clock: Callable[[], datetime],
) -> AcquisitionRunReport: ...

def cmd_run(args: argparse.Namespace) -> int: ...
```

`execute_acquisition_run` validates run state, acquires the run lock, creates the
shared SEC broker, derives bounded worker capacity, and commits each outcome before
starting more work. Network and clock dependencies are injected at the transport/test
seam; the CLI/operator call the same service.

## CLI shape

```bash
python run.py acquisition run --run-id <run-id>
python run.py acquisition run --run-id <run-id> --retry-failures
python run.py acquisition run --run-id <run-id> --workers <count> --artifacts <path>
python run.py acquisition run --run-id <run-id> --json
```

Invoking the CLI command explicitly starts live work; the interactive operator must
separately confirm network execution, defaulting to no. `--workers` is an upper bound
clamped to the resource-derived ceiling. `--retry-failures` explicitly opts into
eligible retries; `--artifacts` overrides the resolved artifact root and `--json`
selects stable machine-readable output.

## Execution contract

- Validate the run and acquire its run lock before opening the network client. A
  lock owned by a live process blocks a second runner. Stale-lock takeover requires
  explicit confirmation that the prior owner has stopped.
- Use one SEC broker per run for request pacing, retries, and failure accounting.
  Derive worker and memory budgets from the shared runtime resource APIs; keep the
  submitted queue and in-flight bodies bounded.
- Stream responses to owner-generated transient paths while enforcing the configured
  byte budget on received content. Hash bytes incrementally. Do not return full
  bodies over process IPC; workers return staged-path references and typed metadata.
- Validate redirect host and accession scope before accepting the response. A
  direct-target HTTP 404 is a failed request (`http_not_found`), not proof that the
  filing did not contain a document; it does not initiate lazy index recovery.
- For direct targets, the fetched document is the selected body. For legacy bundles,
  parse the complete source and select only the exact observed sequence. A complete,
  valid bundle with no matching sequence is `not_filed`; duplicate sequence matches,
  malformed structure, or metadata disagreement are `ambiguous`/failed outcomes as
  specified by typed errors. Never substitute sequence one or select by guesswork.
- The only exception is a catalog-direct primary pinned with
  `exact_form_with_lazy_index`: after the sequence-1 body is fetched, a bounded ASCII
  `<TYPE>` mismatch or an HTML cover evaluator unable to verify the filing form may
  trigger one index fetch. Select a replacement only from a unique recognized index
  row whose `document_type` equals the filing form; record every observed slot/type
  and the target-to-slot assignment. A recognized index with no matching row yields
  index-evidenced `not_filed` for an optional target or `required_missing` for a
  required target; duplicate rows are `ambiguous`; failed lookup/parsing is `failed`.
  `submitted_primary` skips this branch. Positive HTML cover evidence is
  heuristic and does not create a slot type assertion.
- Record response and selected-body digests/sizes separately when extraction creates
  a child body. Pass the selected body by managed transient reference to S10. S9
  does not normalize it or define durable payload storage.
- Commit completed target outcomes as work finishes. Cancellation stops new work,
  cleans partial files, preserves committed results, and leaves unfinished work
  resumable. Remove transient source/selected files after S10 consumes them unless
  explicit fixture capture has retained the source response.
- `--retry-failures` retries only outcomes classified retryable by the transport
  contract. It does not repeat acquired, `not_filed`, `required_missing`, ambiguous,
  or terminally refused work. A later retry does not erase earlier attempt provenance.

## Outcomes and reporting

Each target retains its S6 identity and receives an S9 outcome such as acquired,
`not_filed`, `required_missing`, ambiguous, or failed. Report run identity,
attempted/completed/pending counts, outcome totals, retryable failures, and cancellation.
An acquired result
includes a selected-body handle for the downstream processing handoff; payload bytes
are not embedded in the result record.

The detailed transport and extraction boundaries are separate lower-layer contracts;
see [streaming](transport.md) and [exact sequence selection](extraction.md). Mutable
state, run locking, retries, interruption, and S10 body-consumption receipts are in
[run state](state.md).

## Acceptance

Non-executable targets produce no HTTP request; oversize bodies never become partial
successes; interrupted runs preserve completed results; bundle selection is exact;
and fixture replay can exercise the same selection path without HTTP.

Offline tests cover no-work runs, one direct target, bundle target, optional
`not_filed`, required `required_missing`, lazy-index resolution, 404, retryable and
terminal failures, timeout, response-size breach, active/stale locks,
interruption during transfer and after outcome commit, duplicate target assignment,
and cleanup after S10 consumption. Tests inject a fake stream transport at the
`SecHttpClient`/broker seam and assert no network calls for ineligible targets.

## Detailed contracts

The command is split here because orchestration, response streaming, exact sequence
extraction, run-state persistence, and S10 file handoff each have independent edge
cases and tests:

- [Run state, retries, and body handoff](state.md)
- [Run persistence and SQL](persistence.md)
- [Bounded SEC transport](transport.md)
- [Exact bundle selection](extraction.md)
