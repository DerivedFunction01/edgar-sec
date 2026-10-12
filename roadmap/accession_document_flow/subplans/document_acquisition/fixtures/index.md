# `acquisition fixture`

## Purpose and status

Retain selected acquisition evidence and replay it without network access. The v3
SQLite store, CLI commands, and operator actions for create/fill/list/replay are
implemented. Capture supports direct responses, bundle responses, and complete
lazy-index response groups when their evidence was retained during acquisition; a
bodyless failed attempt can also be captured as metadata. Full response-evidence
retention is opt-in and default-off: run acquisition with
`--retain-response-evidence`. Without it, bundle/lazy response groups may be
unavailable after the run. Historical fixture files under
`tests/fixtures/document_storage/` do not form S9 fixture records and cannot be replayed
through the current store.

## CLI and operator shape

```text
acquisition fixture create --fixture <id>
acquisition fixture fill --fixture <id> --run-id <run-id> --target-id <id> --attempt-id <id> [--max-response-bytes <positive-int>]
acquisition fixture list [--fixture <id>] [--capture-id <id>] [--target-id <id>]
acquisition fixture replay --fixture <id> --capture-id <id> --target-id <id> --output <new-path>
```

For bundle or lazy-index response groups, enable retention on the acquisition run with
`acquisition run --run-id <run-id> --retain-response-evidence`. Fill requires the
evidence to have been retained then; it does not fetch or reconstruct missing responses.

`--json` selects stable machine-readable output and `--artifacts` overrides the
resolved artifact root. The operator exposes the same four actions. Fill asks for a
default-no evidence-retention confirmation; replay asks for a default-no confirmation
before writing its selected output path. Listing is read-only. Create refuses an
existing fixture ID. Fill uses the configured `acquisition.max_response_bytes`
default unless an explicit positive override is supplied.

## Implemented APIs

```python
def create_fixture(fixture_id: str, *, paths: AcquisitionPaths) -> Path: ...

def capture_fixture_case(
    fixture_id: str,
    run_id: str,
    target_id: str,
    attempt_id: str,
    *,
    paths: AcquisitionPaths,
    max_response_bytes: int,
) -> FixtureCaptureResult: ...

def list_fixtures(paths: AcquisitionPaths) -> Iterator[str]: ...

def list_fixture_cases(
    paths: AcquisitionPaths,
    *,
    fixture_id: str | None = None,
    capture_id: str | None = None,
    target_id: str | None = None,
) -> Iterator[FixtureCaseMetadata]: ...

def replay_fixture_case(
    fixture_id: str,
    capture_id: str,
    target_id: str,
    output_path: Path,
    *,
    paths: AcquisitionPaths,
) -> FixtureReplayResult: ...
```

These are case-level services, not an S10 replay staging API. Replay writes acquired
selected bytes to a new caller-chosen file and does not create a managed durable staging
reference or consumption receipt.

## Capture contract

- Capture requires a positive response-byte cap and validates the fixture, run
  manifest/work order, target membership, exact recorded attempt, attempt kind/source,
  and any attempt body path and recorded byte/digest evidence. It makes no SEC request.
- A successful direct-body attempt is captured from its verified retained response.
  A bodyless failed attempt is captured as metadata only. Bundle and
  `exact_form_with_lazy_index` cases can include the complete response group only when
  acquisition retained the required source, index, and selected responses; otherwise
  capture refuses incomplete evidence.
- The capture ID is deterministic from run, target, and attempt identity. Capture and
  case records are immutable; conflicting evidence is refused rather than overwritten.
- Response bodies are streamed into Zstandard-compressed SQLite BLOBs and verified
  before the atomic append. The configured cap applies to uncompressed response bytes.
- Capture accepts only the current unsuperseded attempt group. If a later target attempt
  has superseded that group's terminal attempt, capture refuses it; this is not an
  arbitrary historical-attempt capture API.
- Captured bytes are fixture evidence only. Fill itself does not process bodies or create
  receipts; M7a separately composes fixture replay, S10 processing, and result projection.
  Neither path publishes S11/M9 payloads. Historical corpus/family evaluation and
  acquisition distribution remain separate or gated work.

## Listing and replay

- Listing streams validated fixture IDs and case metadata in deterministic order. The
  optional fixture/capture/target filters narrow results; listing opens stores
  read-only and does not select, decompress, or hash response BLOBs. Opening a store
  still performs SQLite integrity and foreign-key checks.
- Replay resolves the exact fixture/capture/target case and verifies responses using the
  incremental BLOB integrity primitive. Ordinary direct cases check that source and
  selected identities agree; lazy-resolution cases verify the recorded source, index,
  and selected responses separately. Bundle selections are extracted locally and
  checked against selected digest and size.
- Acquired replay writes only to a new explicit caller-selected path and refuses
  existing files. A bodyless failed case returns recorded metadata and creates no
  output file. Replay makes no HTTP request and does not mutate fixture data.
- There is no managed fixture-replay-to-S10 staging API. S11 publication remains gated on
  representative S9/S10 evidence and explicit approval; fixture BLOBs are not snapshot
  payloads.

## Detailed contracts

The command family is split by mutation and integrity boundary:

- [Fill fixture cases](fill.md)
- [List fixture evidence](list.md)
- [Replay a captured case](replay.md)

## Review console

Review artifacts are generated and compared with the shared review console:

```text
acquisition review generate --fixture <id> [--capture-id <id>] [--target-id <id>]
acquisition review compare --base <review-dir> --new <review-dir>
```

The shared run layout contains `manifest.jsonl` and one `processing-review.json` per
case. Review generation is offline and currently requires the captured S9 run body to
remain available; compare uses the same case-level review diff mechanism as inventory.

## Detailed contracts

The command family is split by mutation and integrity boundary:

- [SQLite schema and BLOB lifecycle](storage.md)

Only [fixture storage](storage.md) owns SQL, schema migration, and body persistence;
the capture/list/replay commands call that service rather than execute ad hoc SQL.
