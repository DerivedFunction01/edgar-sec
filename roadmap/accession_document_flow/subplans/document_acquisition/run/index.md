# `acquisition run`

## Purpose and status

Execute pending target work from a validated S9 run and resume it safely after
interruption. The runner performs bounded response transfer and exact-sequence
extraction, then processes each acquired target before releasing the run lock.
Execution is serial; S11 publication remains gated. Catalog-direct direct-body screens
remain unverifiable.
The catalog-direct exact-form selector compares primary bundle `<TYPE>` with the pinned
form using strict ASCII equality; mismatch or unverifiable type enters lazy index
recovery. A recovered bundle candidate must pass the same check. Other selectors do not
screen the submitted primary. Family-aware HTML/cover evaluation remains absent.
Plan-pinned fixture fill, deterministic listing, review generation/comparison, and
offline review analysis are wired; no user-facing replay or body-export command exists.

## UX and service signature

The operator selects a projected run, previews pending/assigned/retryable targets,
then explicitly confirms live SEC access (default no). Retryable acquisition and
processing failures are retried only when `--retry-failures` is selected;
non-retryable, acquired, skipped, ambiguous, `not_filed`, and `required_missing`
targets are not reacquired. The CLI invocation itself authorizes
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

`execute_acquisition_run` validates the work order, derives resource capacity,
acquires the run lock, and commits each target outcome before processing the acquired
checkpoint and continuing. The current runner processes targets serially. The CLI
transport lazily creates the shared SEC broker on the first request, so a run with no
eligible work makes no network request. Network and clock dependencies are injected at
the transport/test seam.

## CLI shape

```bash
python run.py acquisition run --run-id <run-id>
python run.py acquisition run --run-id <run-id> --max-response-bytes <bytes>
python run.py acquisition run --run-id <run-id> --max-response-bytes <bytes> --retry-failures
python run.py acquisition run --run-id <run-id> --max-response-bytes <bytes> --workers <count> --artifacts <path>
python run.py acquisition run --run-id <run-id> --max-response-bytes <bytes> --json
```

Invoking the CLI command explicitly starts live acquisition work; the interactive operator must
separately confirm network execution, defaulting to no. `--workers` is currently an
upper-bound option only; the runner executes serially. `--retry-failures` explicitly
opts into eligible retries; `--artifacts` overrides the resolved artifact root and
`--json` selects stable machine-readable output. The finite response-byte ceiling
defaults to the registered `acquisition.max_response_bytes` setting; an explicit
`--max-response-bytes` value overrides it.

Those flags describe the implemented v1 runner. Operation-aware run schema v2 pins the
response-byte ceiling and fixture/live mode at project time; `run` cannot change them.
A different ceiling or source mode requires a new projected run ID.

## Execution contract

- Validate the run and acquire its run lock before opening the network client. Hold
  the same lock through acquisition and processing for each target. A
  lock owned by a live process blocks a second runner. Stale-lock takeover requires
  explicit confirmation that the prior owner has stopped.
- Use one lazily-created SEC broker per run for request pacing, retries, and failure
  accounting. The current runner processes one target at a time.
- Stream responses to owner-generated transient paths while enforcing the configured
  byte budget on received content. Hash bytes incrementally. Do not return full
  bodies over process IPC; workers return staged-path references and typed metadata.
- Validate redirect host and accession scope before accepting the response. A
  direct-target HTTP 404 is a failed request (`http_not_found`), not proof that the
  filing did not contain a document; it does not initiate lazy index recovery.
- For direct targets, the fetched document is the selected body. For legacy bundles,
  the engine scans the complete source in bounded chunks and writes only the exact
  selected sequence to a staged file. It verifies source integrity and structural
  constraints. Current S6 projections emit no family-trigger IDs/versions, so the runner
  refuses the retained `exact_form_with_lazy_index` branch before any index request.
  Supported work uses a selected direct body or exact bundle sequence; a direct-target
  failure never switches to bundle or index retrieval. The legacy selector field is not
  runtime authority. No HTML/cover evaluator exists.
- Record response and selected-body digests/sizes separately when extraction creates
  a child body. Pass the selected body by managed transient reference to S10. S9
  does not normalize it or define durable payload storage.
- Commit completed target outcomes as work finishes. Cancellation stops new work,
  cleans partial files, preserves committed results, and leaves unfinished work
  resumable. Acquired selected files remain staged after processing; cleanup after
  processing/publication is not yet implemented. The fixture store supports
  compressed response persistence and internal streaming verification. Fixture
  create/fill/list and review generate/compare/analyze commands are wired. Projecting a
  fixture directly into an acquisition run remains a separate contract.
- `--retry-failures` retries acquisition outcomes classified retryable by the transport
  contract and retryable processing operations. It does not repeat acquired, `not_filed`,
  `required_missing`, ambiguous, or terminally refused acquisition work. A later retry
  does not erase earlier attempt provenance or successful processing results.

## Outcomes and reporting

Each target retains its S6 identity and receives an S9 outcome such as acquired,
`not_filed`, `required_missing`, ambiguous, or failed. The run report includes acquisition
outcome totals and processing operation counts, attempts, completion, and success. Report
run identity, attempted/completed/pending counts, retryable failures, and cancellation.
Payload bytes are not embedded in the result record.

The detailed transport and extraction boundaries are separate lower-layer contracts;
see [streaming](transport.md) and [exact sequence selection](extraction.md). Mutable
state, run locking, retries, and interruption are in [run state](state.md). S10
body-consumption receipts are recorded during the combined run; cleanup remains gated.

## Acceptance

Implemented: non-executable targets produce no HTTP request; oversize bodies never
become partial successes; interrupted runs preserve committed outcomes; acquisition
and processing share the run lock; bundle selection is exact; and fixture review uses
plan pins, source-run processing results, and offline analysis. Remaining: verified
HTML/SGML identity-screen behavior, durable snapshot publication, and cleanup
authorization.

Offline tests cover no-work runs, one direct target, bundle target, optional
`not_filed`, required `required_missing`, lazy-index resolution, 404, retryable and
terminal failures, timeout, response-size breach, active/stale locks,
interruption during transfer and after outcome commit, duplicate target assignment,
and refusal of cleanup before publication or explicit discard. Tests inject a fake stream transport at the
`SecHttpClient`/broker seam and assert no network calls for ineligible targets.

## Detailed contracts

The command is split here because orchestration, response streaming, exact sequence
extraction, run-state persistence, and S10 file handoff each have independent edge
cases and tests:

- [Run state, retries, and body handoff](state.md)
- [Run persistence and SQL](persistence.md)
- [Bounded SEC transport](transport.md)
- [Exact bundle selection](extraction.md)
