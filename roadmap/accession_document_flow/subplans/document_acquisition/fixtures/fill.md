# `acquisition fixture fill`

## Purpose and status

Copy every acquired selected body from one recorded S9 run into an immutable, plan-pinned parser fixture. Fill is local and does not require source-response retention or issue SEC requests.

## CLI and operator

```text
acquisition fixture fill --fixture <id> --run-id <run-id>
```

The fixture must be pinned to the run's validated published S6 plan. The operator discovers compatible fixtures and runs, then fills the selected run in one operation. Target IDs, attempt IDs, response limits, and hashes are not operator inputs. The body-size ceiling comes from `acquisition.max_response_bytes`.

```python
def capture_fixture_run(
    fixture_id: str,
    run_id: str,
    *,
    paths: AcquisitionPaths,
    max_body_bytes: int,
) -> FixtureRunCaptureResult: ...
```

## Capture contract

- Validate the fixture plan pin, run manifest, work order, target state, and selected-body handoff before appending bytes.
- Capture only acquired targets with a verified selected staged body. Non-executable and non-acquired targets are skipped; a missing, corrupt, or oversized selected body refuses the fill.
- Store the selected document bytes and parser metadata only. Raw HTTP responses, index pages, bundle containers, failed attempts, and source-response groups stay in S9 run evidence.
- Group all selected target bodies from the run under one deterministic capture identity. Repeated fill of the same run/body set is idempotent; changed bodies produce a distinct capture.
- Stream each selected body through Zstandard into SQLite, deduplicate equal body digests, and append capture/case metadata transactionally. Refuse conflicts and leave existing fixture records unchanged.
- Capture does not mutate S9 run state, delete selected staging files, create processing receipts, or publish S11 payloads.

## Deliberate gaps

- **Historical attempts**: Fill captures the current acquired body for each target, not earlier retries or failed-attempt response data.
- **Missing selected staging**: Fill cannot reconstruct a selected body after its S9 staging file is removed.
- **Production use**: A parser fixture is diagnostic evidence, not production route-budget approval or publisher input.

## Tests

Offline tests cover run-wide capture grouping, selected-body integrity without source-response retention, skipped targets, size refusal, immutable deduplication, and fixture-plan pinning.
