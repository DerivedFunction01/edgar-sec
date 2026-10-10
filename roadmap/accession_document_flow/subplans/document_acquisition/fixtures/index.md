# `acquisition fixture`

## Purpose and status

Explicitly retain selected acquisition evidence and replay it without network access.
The SQLite store, uniform Zstandard response storage, append-only capture records, and
incremental digest-verified replay are implemented. The `fixture` CLI/capture service
remains a TODO until the S9 runner produces acquisition attempts; the legacy
`document_storage` fixture contract is not reusable as S9 state.

## CLI and operator shape

```text
acquisition fixture capture --fixture-id <id> --run-id <run-id> --target-id <id> --attempt-id <id>
acquisition fixture list
acquisition fixture replay --fixture-id <id> --capture-id <id> --target-id <id>
acquisition fixture list --fixture-id <id> --capture-id <id> --target-id <id> --json
```

The interactive `f` console exposes capture, list, and replay. Capture records one
already-completed target attempt at a time. `list` filters are optional; `--json`
selects stable machine-readable output and `--artifacts` overrides the resolved
artifact root.

## UX and service signatures

Fixture capture previews run/target/attempt identity and the source/selected byte
counts before the operator confirms local evidence retention. It never initiates a
SEC request; it promotes an already staged successful source response. Fixture list
is read-only and does not hash all large bodies. Replay takes an exact
fixture/capture/target key and returns a verified staged-body handle; it never prints
the document or creates an HTTP client.

```python
def capture_fixture_case(
    fixture_id: str,
    run_id: str,
    target_id: str,
    attempt_id: str,
    *,
    paths: AcquisitionPaths,
) -> FixtureCaptureResult: ...

def list_fixture_cases(
    fixture_id: str | None,
    *,
    paths: AcquisitionPaths,
) -> tuple[FixtureCaseSummary, ...]: ...

def replay_fixture_case(
    fixture_id: str,
    capture_id: str,
    target_id: str,
    *,
    paths: AcquisitionPaths,
    staging: ManagedStaging,
) -> FixtureReplayResult: ...

def cmd_fixture(args: argparse.Namespace) -> int: ...
```

The detailed schemas and edge cases are separated by mutation boundary below.

## Contract

- Capture is explicit. Ordinary acquisition retains source/selected-body staging
  through S10 and S11 publication; it removes the files only after payload Parquet
  adoption or explicit run discard. Fixture capture separately retains the compressed
  source response as replay evidence in SQLite.
- Store Zstandard-compressed response bytes in SQLite BLOBs. The response digest/size
  identify the exact uncompressed bytes; stored digest/size verify the compressed BLOB.
  There is no parallel body file store; URL metadata, selected digest, target-plan
  provenance, and capture identity are indexed in the same database.
- For bundle targets, retain the source response and replay exact-sequence extraction;
  the selected child can be re-derived and checked against its recorded digest. Do
  not store duplicate body copies merely to replay a selected child.
- Apply Zstandard before SQLite insertion for every route/media type; decompression is
  incremental and verifies the exact uncompressed response digest during replay.
- Same target captured later appends a new capture case; it never overwrites prior
  evidence. Fixture and case IDs resolve only within their fixture root.
- Replay verifies the common manifest envelope, matching manifest/SQLite schema
  versions, provenance, BLOB size and digest, and the pinned extraction/selection
  contract before returning a selected-body handle.
  It performs zero SEC requests and does not mutate the fixture.
- Captured response bodies are test/review evidence, not an S11 durable payload store
  or a published document snapshot. Fixture commands do not expose snapshot-DAG
  publication actions.

## Refusal behavior

Refuse corrupt manifests/indexes, missing or changed content, path traversal,
incompatible schema versions, and target/capture mismatches before returning a body.
A failed acquisition may be recorded as a case without a response body, but replay
cannot produce a selected body for it.

## Acceptance

Replay of an acquired case reproduces the selected bytes/digest with no HTTP client
activity. Appends preserve all earlier fixture evidence, and large-body capture and
replay remain bounded-memory operations.

## Detailed contracts

The fixture command family is split because evidence capture, discovery, replay, and
SQLite/blob lifecycle have distinct mutation and integrity contracts:

- [Capture cases](capture.md)
- [List fixture evidence](list.md)
- [Replay a captured case](replay.md)
- [SQLite schema and BLOB lifecycle](storage.md)

Only [fixture storage](storage.md) owns SQL, schema migration, and body persistence;
the capture/list/replay commands call that service rather than execute ad hoc SQL.
