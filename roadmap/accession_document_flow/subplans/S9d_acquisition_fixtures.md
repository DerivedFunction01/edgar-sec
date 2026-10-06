# S9d — Acquisition Fixture Store and Replay

## Owner and status

- Owning stage in [S9](S9_acquisition.md): append-only review evidence.
- Status: SQLite manifest/case contract with file-backed body fixtures.
- Depends on: [S9a target rows](S9a_target_adapter.md), [S9b staged response bodies](S9b_stream_transport.md), [S9c extraction](S9c_sgml_extraction.md).

## Objective

Capture a selected acquisition corpus with bounded-memory writes and replay it offline. The fixture store is test/review evidence, not a published payload store or the S11 payload design.

## Layout and schemas

```text
{artifacts_root}/acquisition/fixtures/{fixture_id}/
  manifest.json
  cases.sqlite
  responses/{sha256-prefix}/{response_sha256}.body
```

`cases.sqlite` stores metadata and cases; large body files are immutable and content-addressed outside SQLite so appending or replaying a 25 MB response does not materialize it as a BLOB.

```sql
CREATE TABLE acquisition_responses (
    source_url TEXT NOT NULL,
    final_url TEXT NOT NULL,
    response_sha256 TEXT NOT NULL,
    body_size INTEGER NOT NULL CHECK (body_size >= 0),
    content_type TEXT,
    content_encoding TEXT,
    relative_body_path TEXT NOT NULL,
    PRIMARY KEY (source_url, response_sha256)
);

CREATE TABLE acquisition_cases (
    capture_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    plan_id TEXT NOT NULL,
    accession TEXT NOT NULL,
    request_id TEXT NOT NULL,
    target_role TEXT NOT NULL,
    selector TEXT NOT NULL,
    optional INTEGER NOT NULL CHECK (optional IN (0, 1)),
    source_origin TEXT NOT NULL CHECK (source_origin IN ('inventory_index', 'catalog_direct')),
    retrieval_mode TEXT NOT NULL CHECK (retrieval_mode IN ('direct_url', 'bundle_sequence')),
    target_url TEXT,
    effective_document_path TEXT,
    sequence INTEGER,
    selected_sequence INTEGER,
    observed_size INTEGER CHECK (observed_size IS NULL OR observed_size >= 0),
    inventory_entry_id TEXT,
    target_status TEXT NOT NULL CHECK (target_status = 'matched'),
    availability_evidence TEXT NOT NULL,
    acquisition_status TEXT NOT NULL CHECK (acquisition_status IN ('acquired', 'not_filed', 'ambiguous', 'failed')),
    acquisition_source TEXT NOT NULL CHECK (acquisition_source IN ('live_sec', 'fixture_replay')),
    error_code TEXT,
    source_url TEXT,
    response_sha256 TEXT,
    selected_sha256 TEXT,
    selected_size INTEGER CHECK (selected_size IS NULL OR selected_size >= 0),
    selected_filename TEXT,
    captured_at TEXT NOT NULL,
    PRIMARY KEY (capture_id, target_id),
    CHECK (retrieval_mode != 'bundle_sequence' OR sequence > 0),
    CHECK (selected_sequence IS NULL OR selected_sequence = sequence),
    FOREIGN KEY (source_url, response_sha256)
        REFERENCES acquisition_responses(source_url, response_sha256),
    CHECK (acquisition_status != 'acquired' OR
        (response_sha256 IS NOT NULL AND selected_sha256 IS NOT NULL AND selected_size IS NOT NULL))
);
```

The manifest uses `foundation.runtime.fixtures` for dataset-scoped location and the
common `fixture_kind`, `manifest_version`, identity, storage-reference, and timestamp
envelope. Acquisition-specific schema versions, target-plan IDs and digests, source
snapshot/catalog IDs and digests, counts, relative body root, and lineage live under
`details`. `acquisition_cases` records the S6 target identity, selector, source
provenance, and retrieval fields needed for review plus the source and selected-body
evidence; `target_status` is copied from S6 and is never overwritten by
`acquisition_status`. Failed transport cases have no response foreign key. All SQLite
foreign keys are enabled.

## Interfaces

```python
open_acquisition_fixture(path: Path, *, mode: Literal["append", "read_only"]) -> AcquisitionFixture

capture_acquisition_case(
    fixture: AcquisitionFixture,
    capture_id: str,
    target: AcquisitionWork,
    result: AcquisitionResult,
    source_body: StagedBodyRef | None,
) -> None

replay_acquisition_case(
    fixture: AcquisitionFixture,
    capture_id: str,
    target_id: str,
) -> AcquisitionExecution
```

Capture is explicit. A successful captured case requires `source_body`; failures may capture case metadata without a body. The store streams the staged source body into a temporary content-addressed file, verifies the expected digest, atomically installs it, then commits the response/case rows and atomically updates the manifest. A crash may leave an unreferenced body file, but never a manifest row pointing at a partial file. Selected legacy bytes are reproduced by replaying the source response and running the pinned extractor; `selected_sha256` verifies parity without storing a second copy.

Replay opens SQLite read-only, resolves the exact `(capture_id, target_id)`, verifies the response file's path stays beneath the fixture root, and checks size and digest before rerunning the pinned direct/bundle selection. It returns an `AcquisitionExecution` with a `fixture_replay` result and a selected-body handle on success. It makes zero network requests. Same target IDs from later acquisitions append under a new `capture_id`; prior evidence is never replaced.

## Tests

- `acquisition_cases` matches the S6 target ID, plan, accession, request, role, source origin, target status, URL, and sequence contracts; it retains live-versus-fixture acquisition source.
- Repeated captures append; `(capture_id, target_id)` is unique and earlier cases remain unchanged.
- Multi-megabyte fixture copy/replay is chunked and hash-identical; no full-body SQLite BLOB or IPC payload is created.
- Manifest publication occurs only after body installation and transaction commit.
- Missing/tampered bodies, digest/size mismatch, path traversal, wrong schema, and wrong plan digest fail replay closed.
- Replay returns the same selected sequence/output digest using the pinned acquisition/extraction fingerprints and makes zero HTTP requests.
- Non-captured transient responses are removed after processing; the fixture store remains separate from any published payload artifacts.

## Acceptance criteria

Captured raw sources are immutable, content-verified, append-only, path-contained, and replayable without network access. Fixture capture never writes inventory or target-plan tables and does not establish an S11 payload-store design.
