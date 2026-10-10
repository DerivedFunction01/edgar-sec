# `acquisition fixture capture`

## Purpose and status

Append an exact S9 attempt to a named fixture using source bytes already staged by
`acquisition run`. This is design-only; no S9 fixture store exists in tracked code.

## UX and signature

The operator requires a fixture ID, run ID, target ID, and attempt ID. It previews
the outcome, source/selected digests and sizes, and destination; the user must
confirm local evidence retention. Capture does not make SEC requests. The CLI
requires the same four identities, so it cannot silently select a newer retry.

```python
def capture_fixture_attempt(
    fixture_id: str,
    run_id: str,
    target_id: str,
    attempt_id: str,
    *,
    paths: AcquisitionPaths,
) -> FixtureCaseRef: ...

def cmd_fixture_capture(args: argparse.Namespace) -> int: ...
```

The operation raises `FixtureCaptureError` for unknown runs/attempts, non-matching
target identity, missing or digest-mismatched staged response, path escape, or a
fixture schema conflict.

## Capture contract

- Read the attempt and its staged source-response path from the validated S9 run
  ledger. The path must be relative to the run staging root and match recorded
  source digest/size. Never accept an arbitrary caller path.
- Copy exact response bytes into a SQLite BLOB using bounded incremental I/O. Do not
  compress, transform, or create an external body file. Do not store a bundle's
  selected child as a second BLOB; replay re-extracts it and checks its digest.
- Insert/deduplicate the source BLOB and append capture/case metadata in one SQLite
  transaction. Verify the body size/digest before commit; rollback leaves neither a
  partial BLOB nor a visible case row.
- A repeated capture of the same fixture/run/target/attempt with identical metadata
  is idempotent. If the attempt or bytes differ, refuse rather than replace evidence.
  A later acquisition attempt has a distinct attempt ID and appends a new case.
- Failure attempts without a response body may be captured as metadata-only cases.
  They replay the typed failure without HTTP; they cannot produce a body handle.
- Capture does not change the S9 attempt/outcome and does not remove run staging.
  S10's matching body-consumption receipt is the later cleanup boundary.

## Tests

Offline tests cover direct and bundle capture, a malformed/failed response with and
without source bytes, idempotent repeat, new retry attempt, digest and size mismatch,
missing staged path, path traversal, interrupted BLOB write, DB rollback, and
large-body bounded copying. Network fakes are not used by this command.
