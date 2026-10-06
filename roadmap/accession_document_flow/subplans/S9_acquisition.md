# S9 — Target-Plan Acquisition and Source Fixture Database

## Owner and status

- Owning stage in [implementation.md](../implementation.md): **S9**.
- Status: acquisition work-order and source-replay layer; independent of durable
  payload storage.
- Depends on: S6 target plans, S2 acquisition fixture store, S5 snapshot.
- Non-blocking: S10 processing, S11 payload design gate, S12 CLI.

## Objective

Fetch selected documents from a target plan: one direct URL, or the submission
envelope with bundle-plus-sequence extraction. Capture source bytes in an append-only
fixture DB keyed by source URL and body digest, route concurrent requests through one
SEC broker for shared pacing, bound CPU work in a process pool, and establish
response-size and memory limits before enabling large bodies.

## Contract

```text
class Acquirer:
    def fetch(self, target_row) -> AcquiredTarget
    def extract_bundle(self, envelope_bytes, sequence) -> AcquiredTarget
```

Input is one target-plan row and its inventory snapshot. `direct_url` requests one
document. `bundle_sequence` requests the submission envelope and extracts only the
selected child. The full bundle is transport input, not an inventory entry or required
retained output.

The in-memory result carries target identity, status/error, requested and actual
source URL, source kind, response digest/size, selected sequence/filename when
relevant, selected payload digest/size, and the selected raw bytes for the next
processing call. Fetchers report acquisition; they do not choose target roles, judge
content, or persist published outputs.

## Outcomes

Typed, exhaustive outcomes:

- `matched` with `direct_url` or `bundle_sequence`.
- `not_filed`: the target URL exists but the body is absent or the requested
  document is not present.
- `failed`: transient or transport failure.
- `ambiguous`: sequence or filename could not be resolved unambiguously.
- `recovered`: a failed request recovered from saved fixture bytes.

## Fixture database

An append-only SQLite fixture store under
`{artifacts_root}/document_acquisition/fixtures/{fixture_id}/`, separate from the
index-page fixture. Tables:

```sql
CREATE TABLE acquisition_responses (
    source_url TEXT NOT NULL,
    response_sha256 TEXT NOT NULL,
    byte_size INTEGER NOT NULL,
    captured_at TEXT NOT NULL,
    compressed_body BLOB NOT NULL,
    PRIMARY KEY (source_url, response_sha256)
);

CREATE TABLE acquisition_cases (
    target_id TEXT PRIMARY KEY,
    plan_id TEXT NOT NULL,
    accession TEXT NOT NULL,
    requested_url TEXT NOT NULL,
    source_url TEXT,
    response_sha256 TEXT,
    result_status TEXT NOT NULL,
    retrieval_mode TEXT NOT NULL,
    selected_sequence INTEGER,
    selected_filename TEXT,
    selected_sha256 TEXT,
    selected_size INTEGER,
    error_kind TEXT,
    FOREIGN KEY (source_url, response_sha256)
        REFERENCES acquisition_responses (source_url, response_sha256)
);
```

Only the actual HTTP response body is stored in `acquisition_responses`: for a legacy
target this is the complete SGML envelope, from which offline replay extracts the
selected sequence. `selected_sha256` and `selected_size` validate extraction but do
not point to another stored payload. The acquisition fixture contains a small curated
review corpus, not every live fetch. Both fixture stores pin schema version in an
atomic fixture manifest, enable SQLite foreign-key checks, refuse unrelated or
malformed databases, support read-only replay, and never overwrite source evidence.

## Execution

- Route concurrent requests through one SEC broker for shared pacing regardless of the
  fan-out executor.
- Use a bounded process pool for CPU-heavy extraction (SGML envelope parsing,
  sequence lookup).
- The broker currently buffers responses; establish response-size and memory limits
  before enabling large bodies. Add a streaming transport protocol only if real
  acquisition needs it.
- Retry from saved raw bytes with no HTTP.
- No writes to inventory or target-plan artifacts.

## Tests

- Direct and legacy bundle replay.
- Sequence/filename ambiguity handling.
- Missing body.
- Source hash mismatch.
- Fixture append and read-only behavior.
- Retry from saved raw bytes with no HTTP.
- Process serialization.
- Resource-bounded fetch and parse.
- No writes to inventory or target-plan artifacts.
- One broker aggregates all requests for a run.
- Response-size limits enforced before large bodies.
- A failed fetch does not corrupt the fixture store.
- Extraction preserves bundle sequence order exactly.
- Fixture DB refuses an unrelated database.

## Acceptance criteria

Acquisition is an adapter from target-plan rows to fetched bytes with source and
selected-byte provenance, typed missing/failed/ambiguous/recovered outcomes, and an
append-only fixture DB for raw response bytes keyed by source URL and digest. Concurrent
requests are routed through one SEC broker for shared pacing, CPU-heavy extraction
runs in a bounded process pool, and resource limits are established before large
bodies are enabled.
