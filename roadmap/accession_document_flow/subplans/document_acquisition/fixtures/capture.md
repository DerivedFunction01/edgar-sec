# `acquisition fixture capture`

## Purpose and status

Retain exact S9 response evidence in a named fixture for offline replay. The CLI and
operator call the implemented `capture_fixture_case()` service. Persistence primitives
atomically append immutable case metadata and optional streamed response bodies to the
SQLite fixture.

## CLI and operator

```text
acquisition fixture capture --fixture-id <id> --run-id <run-id> --target-id <id> --attempt-id <id> [--max-response-bytes <positive-int>]
```

All four IDs identify the fixture and exact attempt; capture does not silently choose
the latest retry. For bundle and lazy-index cases, acquisition must have been run with
`--retain-response-evidence`; full response-group retention is opt-in and default-off.
The response-byte cap must be positive. The operator collects the same values and
requires explicit affirmative confirmation, defaulting to no, before retaining local
evidence. Capture makes no SEC request.

```python
def capture_fixture_case(
    fixture_id: str,
    run_id: str,
    target_id: str,
    attempt_id: str,
    *,
    paths: AcquisitionPaths,
    max_response_bytes: int,
) -> FixtureCaptureResult: ...
```

## Capture contract

- Validate the named existing fixture, run manifest and work order, target membership,
  exact attempt identity, attempt kind/source, and recorded outcome. The target must
  occur exactly once in the work order and the attempt must belong to that target.
- For a successful direct target, validate the body path as run-staging-contained,
  non-symlink, regular, and consistent with recorded size and digest evidence. For an
  ordinary direct target, the selected body must match the same recorded identity. A
  lazy-resolution group instead validates the distinct selected response against its
  recorded resolution and selected-body identity.
- Successful direct bodies and bodyless failed attempts can be captured. Bundle and
  `exact_form_with_lazy_index` cases can also be captured when acquisition retained the
  complete response group: the source response, any index response, and any selected
  response needed by the recorded resolution. Missing group members cause refusal; a
  failure with any body identity/path is not treated as metadata-only.
- Derive the immutable capture ID deterministically from run ID, target ID, and attempt
  ID. Repeated identical evidence is idempotent; conflicting immutable records or body
  evidence are refused. Capture refuses an attempt group superseded by a later target
  attempt; it does not expose arbitrary historical groups.
- Stream a retained response through Zstandard and atomically append its compressed
  BLOB and case metadata. Verify source and stored sizes/digests before commit; the
  positive response cap bounds uncompressed bytes.
- Capture does not change the S9 attempt/outcome, remove run staging, or create an S10
  receipt/handoff. Fixture evidence is distinct from the S11 payload store and does not
  relax its representative-evidence and approval gate.

## Deliberate gaps

- **S10 handoff and publication**: fixture capture does not provide the separate M5
  receipt/consumer handoff or S10/M7 processing integration, and it does not publish
  S11/M9 payloads. Historical corpus/family evaluation and distribution remain separate
  or gated work.

## Tests

Offline tests cover the fixture persistence primitives and capture orchestration,
including deterministic identity, attempt/work-order validation, retained direct-body
and response-group evidence, metadata-only failures, response limits, immutable
conflicts, and refusals for incomplete or superseded evidence groups.
