# S9 run-state machine and lifecycle

## Purpose and status

This page owns target outcomes, retry, interruption, assignment, and S10 body handoff.
It is design-only. The mutable store and SQL statements are specified in
[run persistence](persistence.md).

## State model

Each projected work-order target has one current outcome and zero or more immutable
attempt records:

| Current outcome | Transition condition | Retry policy |
|---|---|---|
| `pending` | Executable S6 target has not completed an attempt. | Scheduled by default. |
| `skipped` | S6 target is unmatched or has unsupported retrieval mode. | Never scheduled. |
| `acquired` | Direct body downloaded, or exact bundle child extracted and committed. | Never fetched again. |
| `not_filed` | Complete valid bundle has no exact requested sequence, or a recognized lazy index has no row matching an optional target's expected filing form. Record which evidence established absence. | Terminal; not retried. |
| `required_missing` | A recognized lazy index has no row matching the expected filing form for a required target. | Terminal; not retried; run completes with required-target error. |
| `ambiguous` | Duplicate requested sequences or typed source disagreement. | Terminal; not retried. |
| `failed` | Transport, response, source, or extraction failure. | Only if the typed failure is retryable and the caller selects retry. |

`cancelled` is not a target outcome. On cancellation, targets with committed outcomes
remain unchanged and work not yet committed stays pending. A failed attempt remains
in the attempt history if a later retry succeeds.

Run state is derived, not independently edited:

- `invalid`: manifest, work order, state DB, or referenced artifacts fail validation.
- `running`: a valid active run lock is held.
- `ready`: no active lock and no target has an attempt.
- `interrupted`: no active lock and pending targets remain after an attempted run.
- `needs_retry`: no active lock and at least one retryable failure remains.
- `complete_with_errors`: no pending or retryable work remains, but at least one
  non-retryable failure or required-target `required_missing` remains.
- `complete`: no pending, failed, or `required_missing` targets remain; optional
  `not_filed` and `skipped` are terminal outcomes and do not make a run incomplete.

When conditions overlap, derive state in this order: invalid, running, interrupted
with pending targets after an attempted run, `needs_retry`, `complete_with_errors`,
ready for an unattempted run, then complete. Counts still show every retryable and
terminal failure in an interrupted report.

An explicit retry considers only `failed AND retryable` targets. It cannot clear,
rewrite, or bypass the shared SEC failure ledger. A retry blocked by that ledger is
reported as a failure and retains its attempt evidence.

## Persistence API

```python
def initialize_run_state(
    run_dir: Path,
    work_order: Iterable[WorkOrderTarget],
) -> None: ...

def select_run_targets(
    run_id: str,
    *,
    retry_failures: bool,
    paths: AcquisitionPaths,
) -> Iterator[WorkOrderTarget]: ...

def commit_target_attempt(
    run_id: str,
    attempt: AcquisitionAttempt,
    outcome: AcquisitionOutcome,
    *,
    paths: AcquisitionPaths,
) -> None: ...

def inspect_run_state(
    run_id: str,
    *,
    paths: AcquisitionPaths,
) -> AcquisitionStatusReport: ...
```

`initialize_run_state` detects duplicate target IDs while streaming the work order.
`commit_target_attempt` atomically appends the attempt and updates the current target
projection. An acquired result is committed only after its body has a verified
digest, size, and owner-generated run-relative path. A failed DB transaction cannot
leave a partial body reported as acquired.

## Locks and interruption

Acquire an exclusive run lock before making any request. It records run ID, host,
PID, start time, and random owner token. Only its owner token may release it. A
second runner refuses while the lock is valid. A stale local PID can be reclaimed
only after explicit confirmation; a lock from another host is never declared stale
from a remote PID check.

The run loop commits each completed target independently. Ctrl-C and ordinary
shutdown stop scheduling, close the SEC client, remove incomplete temporary files,
and release the lock while preserving completed outcomes. A hard process kill may
leave a stale lock or temporary file; resume validates both and never treats an
uncommitted partial as a success.

## S10 selected-body handoff

The selected file remains staged after S9 acquisition. S10 reads and verifies it,
atomically writes the S9 `BodyConsumptionReceipt` under the path in
[`paths.md`](../paths.md), then removes the selected file. The receipt binds run ID,
target ID, source-response SHA-256, and selected-body SHA-256. S10 also removes a
staged source envelope when one exists; if fixture capture committed it earlier,
the immutable fixture copy remains. S9 status regards absent staged files as
consumed only when a matching receipt exists; a missing staged body without a valid
receipt is corruption. A
processing failure after full input consumption still releases the body but remains
an S10 processing failure, not an S9 acquisition failure.

The full source envelope for a bundle is retained only if a fixture capture commits
it before S10 consumes the selected child. Fixture BLOB retention is recorded in the
fixture index, not by changing the S9 acquisition outcome.

## Tests

Offline state tests cover every transition, index-evidenced optional `not_filed`,
required-target `required_missing`, bundle-evidenced `not_filed`, append-only attempts,
retryable versus terminal failures, repeated retry,
DB rollback after a staged write, concurrent and
stale locks, cancellation, hard-kill recovery, matching/mismatching S10 receipts,
and interrupted target selection. No attempt can update another run's target ID.
