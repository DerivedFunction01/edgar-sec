# `acquisition status`

## Purpose and status

Inspect discovered S9 runs and validate their resumable state without contacting
SEC. Run manifests and state live in the shared transient acquisition root and do not
auto-expire. SQLite state, target selection, and lock inspection primitives are
implemented; the complete status service remains a TODO because manifest/work-order
validation and run discovery are not wired.

## CLI shape

```bash
python run.py acquisition status
python run.py acquisition status --run-id <run-id> --json
python run.py acquisition status --artifacts <path>
```

Without a run ID, show a bounded summary of discovered runs; with one, show its
detailed status and provenance. `--artifacts` overrides the resolved artifact root;
`--json` selects stable machine-readable output.

## Intended UX and unimplemented service signatures

The interactive status action lists run ID, target-plan ID, derived run state, and
progress counts, then lets the operator inspect one run. Detailed status shows S6
pins, schema versions, selected-body lifecycle, last attempt/error per requested
target, and whether a retry is eligible. It never asks for SEC authorization. The
CLI accepts an optional run ID; `--json` uses the same `AcquisitionStatusReport` as
the operator.

```python
def list_acquisition_runs(
    *,
    paths: AcquisitionPaths,
) -> tuple[AcquisitionStatusReport, ...]: ...

def inspect_acquisition_status(
    run_id: str,
    *,
    paths: AcquisitionPaths,
) -> AcquisitionStatusReport: ...

def cmd_status(args: argparse.Namespace) -> int: ...
```

The service raises `AcquisitionStatusError` for an explicitly requested corrupt run.
A list operation may include an invalid summary with its path-safe run ID and error
code, but cannot repair or hide it.

## Contract

- Validate the run manifest, target-plan identity, persisted work order, state
  records, and committed result files before reporting a run as resumable.
- Keep S6 target status separate from acquisition status. Report skipped targets
  independently from executable targets.
- Report progress by outcome: pending, acquired, `not_filed`, `required_missing`,
  ambiguous, failed, and skipped. Show cancellation/interruption and active locks as
  run-level state.
  Distinguish retryable transport failures from terminal or non-retryable outcomes;
  do not infer retryability from a display label.
- Preserve successful target results across interruption. Status inspection never
  mutates checkpoints, resets failures, or starts work.
- Detect an active run lock and expose its owner metadata. Stale-lock recovery is a
  `run` action requiring explicit confirmation, not a side effect of `status`.
- Derive run state from the validated lock/checkpoint and target outcomes: ready,
  running, interrupted, complete, `needs_retry`, or `complete_with_errors`. A run
  with retryable failures is never silently reported as successful or ready for
  downstream consumption.
- Validate a staged selected-body file against recorded size/digest while its body
  lifecycle is `staged`. A file already acknowledged as consumed by S10 may be absent
  without invalidating its successful acquisition result.
- Read status from a consistent read-only snapshot while a run is active. Do not
  repair WAL/journal files, reclaim staging, or change retry counters during inspect.

## Refusal behavior

Invalid run identity, missing or tampered work-order/result files, incompatible
contract versions, and path escapes must be reported as invalid state rather than
repaired during inspection. The status command returns a non-success result for an
explicitly requested invalid run while still permitting a list view to show that
run's invalid summary.

## Acceptance

Two status reads over unchanged run files produce the same report. Inspection is
offline and cannot alter run state.

Offline tests cover an empty run, a run with only skipped targets, acquired targets
with staged and consumed bodies, optional `not_filed`, required `required_missing`,
retryable and terminal failures, a concurrent
active lock, interrupted work, unsupported state schema, a corrupt manifest/part,
and a missing or digest-mismatched staged body. A corrupt explicit run is surfaced
without state repair.
