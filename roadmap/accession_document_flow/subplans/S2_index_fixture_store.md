# S2 — Index-Page Fixture Capture and Replay Store

## Owner and status

- Owning stage in [implementation.md](../implementation.md): **S2**.
- Status: raw-page capture/replay infrastructure; stores bytes and source metadata
  only and is implemented before the empirical audit and production parser.
- Depends on: the cohort adapter (S1) for accession URLs.
- Enables: S0 empirical audit and S3 parser replay.

## Objective

Provide an append-only SQLite fixture store for raw `-index.html` responses and a
read-only replay surface. Capture and fill using the cohort adapter and a shared SEC
transport; replay from the store without HTTP.

## Schema

Three tables, versioned and pinned in an atomic fixture manifest:

```sql
CREATE TABLE index_responses (
    request_url TEXT NOT NULL,
    response_sha256 TEXT NOT NULL,
    byte_size INTEGER NOT NULL,
    captured_at TEXT NOT NULL,
    compressed_body BLOB NOT NULL,
    PRIMARY KEY (request_url, response_sha256)
);

CREATE TABLE index_cases (
    accession TEXT NOT NULL,
    request_url TEXT NOT NULL,
    response_sha256 TEXT NOT NULL,
    PRIMARY KEY (accession, request_url, response_sha256),
    FOREIGN KEY (request_url, response_sha256)
        REFERENCES index_responses (request_url, response_sha256)
);

CREATE TABLE cohort_members (
    accession TEXT NOT NULL,
    source_cik TEXT NOT NULL,
    form TEXT NOT NULL,
    filing_date TEXT NOT NULL,
    report_date TEXT,
    cohort_source_id TEXT NOT NULL,
    PRIMARY KEY (accession, source_cik, cohort_source_id)
);
```

`cohort_source_id` names the catalog plan or dedicated inventory fixture that
contributed the occurrence. `compressed_body` stores the exact response bytes; a digest
key means changed responses append evidence instead of replacing it.

The body codec is zlib; `byte_size` is the uncompressed response length. The digest
is SHA-256 over the uncompressed bytes. A URL with a new digest creates a new immutable
response row, while an identical URL+digest reuses the existing row.

## Fixture manifest

An atomic manifest pinned at commit records the SQLite schema version, fixture ID,
contributing cohort sources, page and accession counts, and the database-relative path.
`foreign_keys` is enabled so SQLite enforces referential integrity.
`page_count` is the number of unique `(request_url, response_sha256)` response rows;
`accession_count` is the number of distinct accessions in `index_cases`.

## Typed models and operations

```python
@dataclass(frozen=True, slots=True)
class IndexResponseKey:
    request_url: str
    response_sha256: str

@dataclass(frozen=True, slots=True)
class CapturedIndexPage:
    accession: AccessionNumber
    key: IndexResponseKey
    body: bytes
    captured_at: datetime

@dataclass(frozen=True, slots=True)
class IndexCaptureFailure:
    accession: AccessionNumber
    request_url: str
    error_code: str

@dataclass(frozen=True, slots=True)
class IndexCaptureResult:
    fixture_id: str
    responses_added: int
    responses_reused: int
    failures: tuple[IndexCaptureFailure, ...]

@dataclass(frozen=True, slots=True)
class IndexFixturePaths:
    database_path: Path
    manifest_path: Path

@dataclass(frozen=True, slots=True)
class IndexFixtureManifest:
    fixture_id: str
    schema_version: int
    database_path: str
    database_sha256: str
    cohort_source_ids: tuple[str, ...]
    page_count: int
    accession_count: int

create_index_fixture(
    paths: IndexFixturePaths,
    *,
    fixture_id: str,
) -> IndexFixtureManifest

capture_index_pages(
    cohort: InventoryCohort,
    *,
    fixture_id: str,
    paths: IndexFixturePaths,
    broker: SecBrokerClient,
) -> IndexCaptureResult

list_index_cases(
    paths: IndexFixturePaths,
    accession: AccessionNumber,
) -> tuple[IndexResponseKey, ...]

replay_index_page(
    paths: IndexFixturePaths,
    accession: AccessionNumber,
    key: IndexResponseKey,
) -> CapturedIndexPage
```

`capture_index_pages` fetches one page per `IndexWorkItem` through the supplied broker
and serializes all SQLite writes in the coordinator. `responses_added` and
`responses_reused` count successful fetched page cases according to whether their
URL+digest required a new response row or matched an existing row; a store hit does
not avoid that fetch. Failures do not
create `index_responses` or `index_cases` rows. Every `CohortObservation` is preserved
in `cohort_members`, including observations whose page request failed.
Replay requires an exact response key,
so an accession with multiple observed digests cannot silently select a version. It
opens SQLite read-only, verifies the schema and response digest, decompresses the
body, and returns the original bytes. The manifest is published atomically only after
the database transaction commits, SQLite is checkpointed, and the database digest is
computed. Its database path is relative to the manifest directory.

## Capture and fill operation

1. Project the cohort with the S1 adapter.
2. Acquire each response through one brokered SEC transport. A worker fetches through
   `SecBrokerClient`, hashes the response, and the coordinator appends a new row.
3. A response whose URL+digest exists is reused; a changed response appends a new row
   keyed by `(request_url, response_sha256)`. Transport failures are recorded as run
   results, not response rows.
4. Write `index_cases` for successful responses and `cohort_members` for every source
   relationship, including failed page requests.

The store never mutates source evidence. Re-fetching a changed response appends; no row
is overwritten. Cohort-member identity is `(accession, source_cik, cohort_source_id)`;
the page fetch identity remains accession/URL, never the CIK relationship.

## Read-only replay

Replay loads the committed database, resolves cases by accession and exact response
key, and serves the original bytes to a chosen parser version. It makes no network
request. Selected cases and the fixture ID drive reproducibility. Wrong-schema or
digest-mismatched databases are refused.

## Tests

- URL+digest dedup: the same response keyed by URL and digest, never duplicated.
- Changed response appends: a new digest adds a row; the old row persists.
- Source-CIK/source-plan union: multiple cohort sources contribute one page.
- Exact byte/hash round trip: stored bytes reproduce the captured digest.
- Read-only non-mutation: replay opens the database read-only and never alters it.
- Wrong-schema refusal: a mismatched schema version is rejected before replay.
- Atomic manifest-after-commit: the manifest reflects a committed database.
- Replay without HTTP: replay resolves cases solely from the fixture store.
- Deterministic case ordering: replay returns cases in a stable order.

## Committed inputs

Commit only the sanitized representative page cases selected by S0 and its small
portable result table. Use local generated databases for the full survey corpus; they
live under a transient path and are not tracked.

## Acceptance criteria

The fixture store is append-only with a URL+digest primary key, supports exact-byte
replay without HTTP, unions source-CIK plan contributions without duplicating pages, refuses
wrong-schema databases, and pins the schema version in an atomic manifest. No source
evidence is ever overwritten.
