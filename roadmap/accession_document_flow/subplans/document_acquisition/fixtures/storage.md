# Acquisition fixture storage

## Purpose and status

Store append-only S9 acquisition evidence for offline replay. This design is not
implemented. One SQLite database owns the cases and raw source-response BLOBs; the
small manifest is a descriptor, not a parallel body store.

## Layout

```text
<artifacts_root>/document_acquisition/fixtures/<fixture_id>/
  manifest.json
  index.sqlite
```

`manifest.json` uses the shared fixture-manifest envelope (`fixture_kind` is
`document_acquisition.source_responses`, storage format `sqlite`, storage path
`index.sqlite`, envelope version 1). Its details pin S9 store-schema version 1. The
manifest is an immutable descriptor with no case list or body digest inventory;
`index.sqlite` owns append-only cases and run/target provenance and independently pins
schema version 1 through `PRAGMA user_version`. The manifest is not a response store.
Its `created_at` and `updated_at` are equal at creation and remain unchanged as case
rows are appended; the SQLite case timestamps are authoritative for captures.
There is no response directory, sidecar body file, compression layer, or body
filename/extension. SQLite's native transaction journal/WAL files, if used, are
database runtime state and never an alternate body store.

## Schema

The initial schema separates unique response bodies from append-only attempts. A body
is identified by the SHA-256 of its exact response bytes; bundle-selected bytes are
re-derived during replay and are not stored as a second copy.

```sql
CREATE TABLE fixture_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE response_bodies (
    body_id INTEGER PRIMARY KEY,
    response_sha256 TEXT NOT NULL UNIQUE,
    byte_size INTEGER NOT NULL CHECK (byte_size >= 0),
    raw_body BLOB NOT NULL,
    CHECK (length(response_sha256) = 64 AND response_sha256 NOT GLOB '*[^0-9a-f]*'),
    CHECK (length(raw_body) = byte_size),
    UNIQUE (response_sha256, byte_size)
);

CREATE TABLE captures (
    capture_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    target_plan_id TEXT NOT NULL,
    target_plan_digest TEXT NOT NULL,
    target_plan_schema_version TEXT NOT NULL,
    inventory_snapshot_id TEXT,
    inventory_snapshot_digest TEXT,
    captured_at_utc TEXT NOT NULL,
    CHECK ((inventory_snapshot_id IS NULL) = (inventory_snapshot_digest IS NULL))
);

CREATE TABLE cases (
    capture_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    attempt_id TEXT NOT NULL,
    accession TEXT NOT NULL,
    request_id TEXT NOT NULL,
    target_role TEXT NOT NULL,
    target_type TEXT NOT NULL,
    optional INTEGER NOT NULL CHECK (optional IN (0, 1)),
    source_origin TEXT NOT NULL CHECK (source_origin IN ('inventory_index', 'catalog_direct')),
    target_status TEXT NOT NULL CHECK (target_status = 'matched'),
    retrieval_mode TEXT NOT NULL CHECK (retrieval_mode IN ('direct_url', 'bundle_sequence')),
    target_url TEXT,
    final_url TEXT,
    sequence INTEGER,
    acquisition_status TEXT NOT NULL CHECK (acquisition_status IN ('acquired', 'not_filed', 'ambiguous', 'failed')),
    error_code TEXT,
    response_sha256 TEXT,
    source_byte_size INTEGER CHECK (source_byte_size IS NULL OR source_byte_size >= 0),
    selected_sha256 TEXT,
    selected_byte_size INTEGER CHECK (selected_byte_size IS NULL OR selected_byte_size >= 0),
    selected_filename TEXT,
    content_type TEXT,
    content_encoding TEXT,
    PRIMARY KEY (capture_id, target_id),
    FOREIGN KEY (capture_id) REFERENCES captures(capture_id),
    FOREIGN KEY (response_sha256, source_byte_size)
        REFERENCES response_bodies(response_sha256, byte_size),
    CHECK ((response_sha256 IS NULL) = (source_byte_size IS NULL)),
    CHECK ((selected_sha256 IS NULL) = (selected_byte_size IS NULL)),
    CHECK ((retrieval_mode = 'direct_url' AND sequence IS NULL) OR
        (retrieval_mode = 'bundle_sequence' AND sequence IS NOT NULL AND sequence > 0)),
    CHECK (response_sha256 IS NULL OR
        (length(response_sha256) = 64 AND response_sha256 NOT GLOB '*[^0-9a-f]*')),
    CHECK (selected_sha256 IS NULL OR
        (length(selected_sha256) = 64 AND selected_sha256 NOT GLOB '*[^0-9a-f]*')),
    CHECK (acquisition_status != 'not_filed' OR retrieval_mode = 'bundle_sequence'),
    CHECK (acquisition_status != 'acquired' OR
        (response_sha256 IS NOT NULL AND source_byte_size IS NOT NULL AND
         selected_sha256 IS NOT NULL AND selected_byte_size IS NOT NULL AND
         selected_filename IS NOT NULL)),
    CHECK (acquisition_status != 'acquired' OR retrieval_mode != 'direct_url' OR
        (response_sha256 = selected_sha256 AND source_byte_size = selected_byte_size))
);
```

The case schema also retains the S6 target identity/provenance needed by review; the
capture pins the target-plan and optional inventory inputs once per captured run.
Failed attempts may have no response row. Direct-target selected and source digests
and sizes agree. A bundle case stores the full response once and records the selected
child digest/size for replay verification.

## Contracts

- **Exact bytes**: `raw_body` contains the exact bytes from the S9 staged source body,
  without additional compression, transformation, newline conversion, or wrapper
  format. `byte_size` and SHA-256 are computed over those same bytes.
- **Single body store**: `index.sqlite` is the sole store for cases and response bytes.
  `manifest.json` is an immutable descriptor only. SQLite may use native transaction
  files, but no application-managed body files or content-addressed directory exists.
- **Bounded capture/replay**: reserve the known BLOB length with `zeroblob`, then use
  incremental SQLite BLOB I/O or an equivalent bounded chunk API to copy between the
  already-staged source and the BLOB. Never materialize a complete response in Python
  memory. Enforce the finite acquisition response bound and SQLite's configured BLOB
  limit before insertion.
- **Atomic append**: insert a new deduplicated response BLOB and its attempt/capture
  rows in one SQLite transaction. Verify size and digest before commit; rollback leaves
  no partial body or visible case. Verify an existing digest's BLOB before deduplicated
  reuse. Existing case keys and bytes are never overwritten.
- **Fixture creation marker**: initialize the SQLite schema and `user_version` before
  atomically writing `manifest.json`. A missing/invalid manifest or database is an
  incomplete fixture and is refused, not auto-repaired.
- **Replay verification**: open the fixture read-only, validate `user_version`, foreign
  keys, IDs and provenance, then stream the selected BLOB while checking its size and
  digest. Bundle replay re-runs the pinned sequence extractor and checks selected
  digest/size; replay makes zero HTTP requests and changes no fixture state.
- **Bound SQL inputs**: bind all values. Enable foreign keys on every connection and
  refuse unrelated databases or unsupported schema versions.
- **Metadata-only failures**: a case without source bytes records its typed outcome
  and cannot return a body handle.

## Deliberate gaps

- **Fixture export/import**: no standalone fixture archive format is defined; copy or
  move the closed SQLite database as one unit until an explicit interchange contract
  is designed.
- **Production payload storage**: fixture BLOB choices are review/replay-specific and
  do not select S11's durable document-payload architecture.

## Acceptance

Capture and replay preserve byte-identical source responses using bounded memory;
database rollback cannot expose partial evidence; duplicate response digests do not
duplicate stored BLOBs; and the fixture directory contains no external body files.
