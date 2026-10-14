# Acquisition fixture storage

## Purpose and status

Store only selected parser-input bodies and the target metadata needed for offline acquisition-parser review.

**Implemented:** plan-pinned schema v2, append-only run captures, deduplicated Zstandard body storage, bounded integrity verification, run-level fill from staged S9 bodies, deterministic discovery, and offline parser review. The fixture does not retain source response groups, error cases, or acquisition processing outputs.

Fill reads each acquired target's selected staged body directly. It does not require `--retain-response-evidence`, initiate SEC requests, or ask the operator to enter target, attempt, capture, or digest values. Non-acquired targets are skipped; acquired targets with missing or invalid staged bodies fail closed.

## Layout

```text
<artifacts_root>/document_acquisition/fixtures/<fixture_id>/
  manifest.json
  fixture.sqlite
```

`manifest.json` uses the shared fixture envelope with `fixture_kind=document_acquisition.parser_bodies`. Store schema version 2 is pinned independently by the manifest details and SQLite `user_version`. The fixture manifest and `fixture_meta` pin the published S6 target plan. Schema v1 is rejected; there is no migration or dual-version reader.

The SQLite tables are `fixture_meta`, `body_blobs`, `captures`, and `cases`. A capture identifies one run snapshot; its cases identify acquired targets, their selected-body attempt, parsing metadata, and a body digest/size. Identical body bytes share one compressed BLOB.

## Contracts

- **Parser input only**: A fixture body is the selected staged document body, not the original HTTP response, lazy-index page, or bundle container.
- **Run-scoped fill**: Fill enumerates the validated work order and captures every acquired target with a verified selected staged body. It never exposes per-target or per-attempt selection.
- **Stable capture**: Capture identity is derived from the run and its selected target/attempt/body identities. Repeating fill is idempotent; a changed acquired-body set creates a distinct capture.
- **Exact bytes**: `body_sha256` and `byte_size` identify uncompressed selected-body bytes. `stored_sha256` and `stored_byte_size` verify the Zstandard BLOB.
- **Bounded storage**: Stream selected bytes through compression into a transient file, reserve the SQLite BLOB, and copy it with incremental BLOB I/O. Decompress incrementally for review verification.
- **Immutable append**: Capture and case metadata and body BLOBs are inserted transactionally. Existing identities are never overwritten; conflicting metadata or bytes are refused.
- **Plan pin**: Capture refuses a run whose S6 plan ID, digest, or schema version differs from the fixture pin.
- **Offline review**: Parser review verifies the body BLOB, then invokes current acquisition-engine handlers directly. It does not use source-run S10 outputs, receipts, or projections.
- **No compatibility path**: Old response-group fixtures and their target/attempt capture workflows are not read or migrated.

## Deliberate gaps

- **Response-history review**: The fixture keeps only the selected parser body. Inspecting raw responses, lazy-index evidence, or failed attempts remains a run-evidence task.
- **Fixture interchange**: No separate archive/import format is defined; a closed SQLite fixture is the storage unit.
- **Publication**: Parser-review artifacts are diagnostic only and are not production snapshots or publisher input.

## Acceptance

Tests cover selected staged-body capture without retained raw responses, run-wide capture grouping, immutable body deduplication, stale-schema rejection, body integrity verification, and offline handler execution from fixture bytes. Production parser budgets and publication remain separately gated by representative evidence and approval.
