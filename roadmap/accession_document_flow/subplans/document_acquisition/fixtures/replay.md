# `acquisition fixture replay`

## Purpose and status

Reproduce one captured acquisition attempt from local evidence and return its typed
outcome with no network access. This is design-only; no S9 replay adapter exists in
tracked code.

## UX and signature

The operator selects exact fixture, capture, and target IDs; it displays the recorded
retrieval mode/outcome and confirms that replay is offline. The CLI requires the same
IDs. Successful replay returns a staged-body handle to a caller and prints metadata,
never body bytes.

```python
def replay_fixture_case(
    fixture_id: str,
    capture_id: str,
    target_id: str,
    *,
    paths: AcquisitionPaths,
    staging: ManagedStaging,
) -> FixtureReplayResult: ...

def cmd_fixture_replay(args: argparse.Namespace) -> int: ...
```

`FixtureReplayResult` carries `source="fixture_replay"`, the recorded S9 outcome,
and a `StagedBodyRef` only when the selected body was reproduced successfully.

## Verification and route behavior

- Resolve the exact row from the fixture index using bound IDs. Verify fixture/run
  provenance, supported schema, source/selected digests and byte sizes, and BLOB
  presence before returning a staged-body handle.
- Direct targets use the captured response as the selected body; source and selected
  digests must agree unless a catalog-direct lazy resolution selected a different
  physical slot.
- Catalog-direct `exact_form_with_lazy_index` replay validates the captured sequence-1
  body, reruns the version-pinned local screen and lazy index parser, verifies the
  matching entry set and resolution outcome, then returns the captured replacement
  body's bytes when one was acquired. It makes no index request. `submitted_primary`
  replays sequence 1 without a type screen.
- Bundle targets rerun the same streaming sequence extractor over the captured full
  response. Verify the recorded sequence, source digest, selected digest, and selected
  byte count. No filename/role guess or sequence fallback is permitted.
- Captured `not_filed`, `required_missing`, ambiguous, and failure cases reproduce their typed S9
  outcome. Cases with no response body replay the recorded failure metadata only.
- Any corrupt or mismatched evidence fails before returning a body. Replay never
  edits the fixture database, resets an acquisition run, or constructs
  `SecHttpClient`.
- Both direct and bundle-selected bytes are written to a generated staging path from
  the read-only BLOB stream and cleaned after their S10 consumption receipt. The
  fixture database remains unchanged.

## Tests

Tests assert byte-identical direct replay, exact bundle-child replay and digest,
zero HTTP calls, typed replay of absent/required-missing/ambiguous/malformed outcomes,
lazy-index resolution and replacement-body replay, refusal on a
changed BLOB/schema/provenance, and cleanup of generated staging after S10
acknowledgement. Repeated replay leaves fixture metadata unchanged.
