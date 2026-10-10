# Acquisition fixture storage

## Purpose and status

Store append-only S9 acquisition evidence for offline replay. This design is not
implemented. One SQLite database owns the cases and raw source-response BLOBs; the
small manifest is a descriptor, not a parallel body store.

## Layout

```text
<artifacts_root>/document_acquisition/fixtures/<fixture_id>/
  manifest.json
  fixture.sqlite
```

`manifest.json` uses the shared fixture-manifest envelope (`fixture_kind` is
`document_acquisition.source_responses`, storage format `sqlite`, storage path
`fixture.sqlite`, envelope version 1). Its details pin S9 store-schema version 2. The
manifest is an immutable descriptor with no case list or body digest inventory;
`fixture.sqlite` owns append-only cases and run/target provenance and independently pins
schema version 2 through `PRAGMA user_version`. The manifest is not a response store.
Its `created_at` and `updated_at` are equal at creation and remain unchanged as case
rows are appended; the SQLite case timestamps are authoritative for captures.
There is no response directory, sidecar body file, or body filename/extension. Every
captured response is Zstandard-compressed before insertion; the same policy applies to
HTML/text, XML, PDF, images, and other media. SQLite's native transaction journal/WAL
files, if used, are database runtime state and never an alternate body store.

## Schema

The schema separates unique response bodies from append-only cases. A body is
identified by the SHA-256 of its exact response bytes. Bundle-selected children are
re-derived during replay and are not stored as a second copy; direct sequence-2
recovery bodies and lazy index responses are separately referenced response bodies.

```sql
CREATE TABLE fixture_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE response_bodies (
    body_id INTEGER PRIMARY KEY,
    response_sha256 TEXT NOT NULL UNIQUE,
    byte_size INTEGER NOT NULL CHECK (byte_size >= 0),
    storage_codec TEXT NOT NULL CHECK (storage_codec = 'zstd'),
    stored_sha256 TEXT NOT NULL,
    stored_byte_size INTEGER NOT NULL CHECK (stored_byte_size >= 0),
    compressed_body BLOB NOT NULL,
    CHECK (length(response_sha256) = 64 AND response_sha256 NOT GLOB '*[^0-9a-f]*'),
    CHECK (length(stored_sha256) = 64 AND stored_sha256 NOT GLOB '*[^0-9a-f]*'),
    CHECK (length(compressed_body) = stored_byte_size),
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
    form TEXT NOT NULL,
    request_id TEXT NOT NULL,
    target_role TEXT NOT NULL,
    target_type TEXT NOT NULL,
    optional INTEGER NOT NULL CHECK (optional IN (0, 1)),
    catalog_direct_selection TEXT CHECK (catalog_direct_selection IS NULL OR catalog_direct_selection IN ('submitted_primary', 'exact_form_with_lazy_index')),
    source_origin TEXT NOT NULL CHECK (source_origin IN ('inventory_index', 'catalog_direct')),
    target_status TEXT NOT NULL CHECK (target_status = 'matched'),
    retrieval_mode TEXT NOT NULL CHECK (retrieval_mode IN ('direct_url', 'bundle_sequence')),
    target_url TEXT,
    final_url TEXT,
    sequence INTEGER,
    acquisition_status TEXT NOT NULL CHECK (acquisition_status IN ('acquired', 'not_filed', 'required_missing', 'ambiguous', 'failed')),
    error_code TEXT,
    response_sha256 TEXT,
    index_response_sha256 TEXT,
    selected_response_sha256 TEXT,
    resolution_schema_version TEXT,
    screen_kind TEXT,
    screen_result TEXT,
    evaluator_version TEXT,
    index_parser_version TEXT,
    matching_entry_ids_json TEXT,
    selected_sequence INTEGER,
    selected_retrieval_mode TEXT,
    selected_url TEXT,
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
    FOREIGN KEY (index_response_sha256) REFERENCES response_bodies(response_sha256),
    FOREIGN KEY (selected_response_sha256) REFERENCES response_bodies(response_sha256),
    CHECK ((response_sha256 IS NULL) = (source_byte_size IS NULL)),
    CHECK ((selected_sha256 IS NULL) = (selected_byte_size IS NULL)),
    CHECK ((retrieval_mode = 'direct_url' AND sequence IS NULL) OR
        (retrieval_mode = 'bundle_sequence' AND sequence IS NOT NULL AND sequence > 0)),
    CHECK (response_sha256 IS NULL OR
        (length(response_sha256) = 64 AND response_sha256 NOT GLOB '*[^0-9a-f]*')),
    CHECK (selected_sha256 IS NULL OR
        (length(selected_sha256) = 64 AND selected_sha256 NOT GLOB '*[^0-9a-f]*')),
    CHECK (acquisition_status != 'not_filed' OR retrieval_mode = 'bundle_sequence' OR
        (optional = 1 AND catalog_direct_selection = 'exact_form_with_lazy_index' AND
         index_response_sha256 IS NOT NULL)),
    CHECK (acquisition_status != 'required_missing' OR
        (optional = 0 AND catalog_direct_selection = 'exact_form_with_lazy_index' AND
         index_response_sha256 IS NOT NULL)),
    CHECK (acquisition_status != 'acquired' OR
        (response_sha256 IS NOT NULL AND source_byte_size IS NOT NULL AND
         selected_sha256 IS NOT NULL AND selected_byte_size IS NOT NULL AND
         selected_filename IS NOT NULL)),
    CHECK (acquisition_status != 'acquired' OR retrieval_mode != 'direct_url' OR
        (response_sha256 = selected_sha256 AND source_byte_size = selected_byte_size))
);
```

`cases.response_sha256` and `cases.source_byte_size` reference the
uncompressed response identity. The case schema does not use the compressed-storage
digest as the selected document identity.

The case schema also retains the S6 target identity/provenance needed by review; the
capture pins the target-plan and optional inventory inputs once per captured run.
Failed attempts may have no response row. `response_sha256` and `byte_size` identify
the uncompressed exact response. `stored_sha256` and `stored_byte_size` verify the
compressed BLOB before decompression. Direct-target selected and source digests and
sizes agree. A bundle case stores the compressed full response once and records the
selected child digest/size for replay verification.

## Contracts

- **Exact bytes**: `compressed_body` is the Zstandard encoding of the exact S9 staged
  source body. `byte_size` and `response_sha256` identify the uncompressed source;
  `stored_byte_size` and `stored_sha256` verify the stored compressed stream. Replay
  decompresses incrementally, then verifies the uncompressed identity.
- **Single body store**: `fixture.sqlite` is the sole store for cases and compressed
  response bytes.
  `manifest.json` is an immutable descriptor only. SQLite may use native transaction
  files, but no application-managed body files or external payload directory exists.
- **Uniform compression**: compress every response with Zstandard before insertion;
  do not branch on MIME type or assume already-compressed media makes compression
  optional.
- **Bounded capture/replay**: stream the source through a Zstandard encoder into a
  transient compressed staging file to determine stored size/digest, reserve that BLOB
  length with `zeroblob`, then use incremental SQLite BLOB I/O or an equivalent
  bounded chunk API to copy compressed bytes. Remove the staging file after commit.
  Decompress incrementally on replay. Never materialize a complete compressed or
  uncompressed response in Python memory. Enforce the acquisition limit on
  uncompressed bytes and SQLite's configured BLOB limit on stored bytes.
- **Atomic append**: insert a new deduplicated compressed response BLOB and its
  attempt/capture rows in one SQLite transaction. Verify stored and uncompressed sizes
  and digests before commit; rollback leaves no partial body or visible case. Decode
  and verify an existing digest's compressed BLOB before deduplicated reuse. Existing
  case keys and bytes are never overwritten.
- **Fixture creation marker**: initialize the SQLite schema and `user_version` before
  atomically writing `manifest.json`. A missing/invalid manifest or database is an
  incomplete fixture and is refused, not auto-repaired.
- **Replay verification**: open the fixture read-only, validate `user_version`, foreign
  keys, IDs and provenance, then stream the captured initial body and any lazy index
  response. Lazy recovery re-runs the pinned parser and selector, verifies the chosen
  entry/sequence, and replays any separately fetched replacement body. Bundle replay
  re-runs the pinned sequence extractor and checks selected digest/size; all replay
  makes zero HTTP requests and changes no fixture state.
- **Bound SQL inputs**: bind all values. Enable foreign keys on every connection and
  refuse unrelated databases or unsupported schema versions.
- **Metadata-only failures**: a case without source bytes records its typed outcome
  and cannot return a body handle.

## Deliberate gaps

- **Fixture export/import**: no standalone fixture archive format is defined; copy or
  move the closed SQLite database as one unit until an explicit interchange contract
  is designed.
- **Production payload relation**: fixture SQLite is the replay-only compressed BLOB
  store; production snapshot payloads use separate binary/text Parquet relations as
  specified by [the acquisition lifecycle](../lifecycle.md).

## Acceptance

Capture and replay preserve byte-identical source responses using bounded memory;
database rollback cannot expose partial evidence; duplicate response digests do not
duplicate stored BLOBs; Zstandard integrity and uncompressed digest checks pass for
text and binary media; and the fixture directory contains no external body files.
