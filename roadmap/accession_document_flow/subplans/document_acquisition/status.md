# `acquisition status`

## Purpose and status

Inspect discovered S9 runs and validate their resumable state without contacting
SEC. Run manifests and state live in the shared transient acquisition root and do not
auto-expire. Sorted run discovery, manifest/work-order validation, aggregate run-state
inspection, and exact target-attempt inspection are implemented in human/JSON output.

## CLI shape

```bash
python run.py acquisition status
python run.py acquisition status --run-id <run-id> --json
python run.py acquisition status --run-id <run-id> --target-id <target-id> --json
python run.py acquisition status --artifacts <path>
```

Without a run ID, list discovered runs in sorted order; with one, inspect that run.
Adding `--target-id` lists its chronological attempts so a fixture capture command can
reference an exact attempt. Raw response retention is opt-in and defaults off; bundle
and lazy-index response-group capture requires `--retain-response-evidence` on the run.
Output includes run ID, derived state, aggregate target counts, retryable and terminal
failure counts, and active-lock host/PID/time without the lock owner token. Invalid
work-order or manifest state is reported and returns a nonzero result. `--artifacts`
overrides the resolved artifact root; `--json` selects stable machine-readable output.

## Deferred status detail

The operator prompts for a run ID or an empty value to list all runs; after a run ID,
an optional target ID selects attempt history. Selected-body lifecycle and retry
eligibility are deferred; status never repairs a run or starts acquisition. No mode
asks for SEC authorization.

## Contracts

- **Validated summary**: Status validates the run manifest and work order before reading the SQLite state projection.
- **Read-only inspection**: Status never repairs run artifacts, changes checkpoints, or starts acquisition.
- **Aggregate outcomes**: Reports preserve distinct acquisition outcome counts and derived run states, including retryable and terminal failure counts.
- **Lock secrecy**: Active lock output includes host, PID, and start time but omits its owner token; stale-lock recovery remains a separate confirmed run action.
- **Stable discovery**: Unfiltered run discovery is sorted by safe run ID; an explicitly invalid run is reported with a nonzero result.
- **Attempt privacy**: Target detail shows exact attempt IDs, outcomes, errors, timestamps, and digests without exposing body paths or contents.

## Refusal behavior

Invalid run identity, missing or tampered manifests/work orders, incompatible state
schemas, and unsafe run roots are reported as invalid state rather than repaired. A list
view may include an invalid summary; explicitly requesting an invalid run returns a
non-success result.

## Deliberate gaps

- Status does not verify each selected-body file against its recorded digest or size; that lifecycle check needs a separate S9/S10 handoff contract.

## Acceptance

Two status reads over unchanged run files produce the same report. Inspection is
offline and cannot alter run state.

Offline CLI tests cover sorted valid-run discovery, target-specific attempt IDs, unknown
target refusal, corrupt-work-order refusal, and omission of the active lock owner token.
Run-state unit tests cover outcome and lock projection independently.
