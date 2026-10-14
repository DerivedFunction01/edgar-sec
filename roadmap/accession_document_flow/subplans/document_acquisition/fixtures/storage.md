# Acquisition fixture storage

## Purpose and status

Store selected parser inputs and any lazy-index page required to resolve them for offline
acquisition-parser review.

**Implemented:** plan-pinned schema v3, direct plan-driven capture, deduplicated Zstandard
body storage, verified lazy-index caching, deterministic discovery, and offline parser
review. Fixture fill does not require an acquisition run.

## Layout

```text
<artifacts_root>/document_acquisition/fixtures/<fixture_id>/
  manifest.json
  fixture.sqlite
```

`manifest.json` uses the shared fixture envelope with
`fixture_kind=document_acquisition.parser_bodies`. Store schema version 3 is pinned
independently by the manifest details and SQLite `user_version`. The manifest and
`fixture_meta` pin the published S6 target plan. Earlier store versions are rejected;
there is no migration or dual-version reader.

The SQLite tables are `fixture_meta`, `body_blobs`, `captures`, `lazy_indexes`, and
`cases`. A capture groups selected target bodies from a plan-fill invocation. Lazy index
pages are cached once per accession and share the content-addressed compressed BLOB
store with selected bodies.

## Contracts

- **Parser input**: A case BLOB contains the exact selected document bytes consumed by
  offline parser review; an index BLOB is stored only when exact-form lazy resolution uses
  it.
- **Plan-scoped fill**: Fill revalidates the pinned S6 bundle, fetches executable targets
  directly, and creates no run, attempt, or processing receipt.
- **Lazy-index cache**: Exact-form lazy targets without an inventory entry fetch an index
  once per accession; later targets reuse the fixture page and record its digest.
- **Exact bytes**: `body_sha256`/`byte_size` identify uncompressed bytes;
  `stored_sha256`/`stored_byte_size` verify each Zstandard BLOB.
- **Bounded storage**: Stream bytes through compression and incremental SQLite BLOB I/O;
  decompress incrementally for integrity verification.
- **Immutable append**: Capture, case, index, and body records cannot be overwritten;
  equal content shares a BLOB.
- **Serialized fill**: Concurrent plan fills for one fixture are refused while another
  fill holds the fixture lock.
- **Offline review**: Review verifies selected bodies and referenced lazy-index BLOBs before
  invoking current acquisition-engine handlers. It uses no S9 run outputs.

## Deliberate gaps

- **Request history**: Ordinary source responses, bundle containers, and failed HTTP
  attempts are not retained.
- **Fixture interchange**: No separate archive/import format is defined; a closed SQLite
  fixture is the storage unit.
- **Publication**: Parser-review artifacts are diagnostic only and are not production
  snapshots or publisher input.

## Acceptance

Tests cover direct plan capture without run state, lazy-index caching and verification,
immutable body deduplication, stale-schema rejection, and offline handler execution from
fixture bytes. Production parser budgets and publication remain separately gated by
representative evidence and approval.
