# S2 — Index-Page Fixture Capture and Replay Store

## Owner and status

- Owning stage in [implementation.md](../implementation.md): **S2**.
- Status: capture implementation exists and read-only replay returns exact uncompressed
  bytes. A whole-database digest remains optional for appendable fixtures.
- Depends on: the cohort adapter (S1) for accession URLs.
- Enables: S0 empirical audit, S7a fixture CLI, and S7b parser replay/review.

## Objective

Provide an append-only SQLite fixture store for raw `-index.html` responses and a
read-only replay surface. Capture and fill using the cohort adapter and a shared SEC
transport; replay from the store without HTTP.

## Schema

Three tables with a SQLite schema version recorded in an atomic fixture manifest:

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
contributed the occurrence. `compressed_body` stores a zstd frame of the exact response
bytes; a digest key means changed responses append evidence instead of replacing it.

The body codec is zstd; `byte_size` is the uncompressed response length. The digest
is SHA-256 over the uncompressed bytes. A URL with a new digest creates a new immutable
response row, while an identical URL+digest reuses the existing row.

## Fixture manifest

Fixtures live at `{artifacts_root}/document_inventory/fixtures/{fixture_id}/` and
use the shared `foundation.runtime.fixtures` location resolver and manifest envelope.
The envelope records `fixture_kind`, `manifest_version`, fixture identity, the relative
SQLite storage path, and timestamps. Inventory-specific `details` record the store
schema version, capture state, contributing cohort sources, and page/accession/member
counts. `foreign_keys` is enabled so SQLite enforces referential integrity.
`page_count` is the number of unique `(request_url, response_sha256)` response rows;
`accession_count` is the number of distinct accessions in `index_cases`.

## Typed models and operations

```python
from edgar_sec.foundation.runtime.fixtures import FixturePaths

@dataclass(frozen=True, slots=True)
class IndexResponseKey:
    request_url: str
    response_sha256: str

@dataclass(frozen=True, slots=True)
class CapturedIndexCase:
    accession: AccessionNumber
    key: IndexResponseKey

@dataclass(frozen=True, slots=True)
class CapturedIndexPage:
    accession: AccessionNumber
    key: IndexResponseKey
    body: bytes
    captured_at: str

class IndexFixtureReader:
    def list_cases(self, accession: AccessionNumber | str) -> tuple[CapturedIndexCase, ...]: ...
    def iter_cases(self, accession: AccessionNumber | str | None = None, *, batch_size: int = 128) -> Iterator[CapturedIndexCase]: ...
    def replay(self, accession: AccessionNumber, key: IndexResponseKey) -> CapturedIndexPage: ...
    def __enter__(self) -> Self: ...
    def __exit__(self, exc_type, exc_value, traceback) -> None: ...

open_index_fixture(paths: FixturePaths) -> IndexFixtureReader

@dataclass(frozen=True, slots=True)
class FixtureContribution:
    plan_id: str
    catalog_id: str
    scope: str
    plan_schema_version: str
    request_fingerprint: str
    accession_count: int

@dataclass(frozen=True, slots=True)
class FixtureManifestContribution:
    plan_id: str
    catalog_id: str
    scope: str
    plan_schema_version: str
    request_fingerprint: str
    accession_count: int
    captured_accessions: int
    failed_accessions: int
    state: str
    started_at: str
    finished_at: str | None

@dataclass(frozen=True, slots=True)
class IndexFixtureManifest:
    fixture_id: str
    schema_version: int
    capture_state: str
    contributions: tuple[FixtureManifestContribution, ...]
    page_count: int
    accession_count: int
    membership_count: int

@dataclass(frozen=True, slots=True)
class IndexCaptureFailure:
    accession: AccessionNumber
    failure_code: str
    raw_broker_error: str | None

@dataclass(frozen=True, slots=True)
class IndexCaptureResult:
    responses_added: int
    responses_reused: int
    responses_processed: int
    cases_created: int
    members_created: int
    failures: tuple[IndexCaptureFailure, ...]

create_index_fixture(
    paths: FixturePaths,
    *,
    fixture_id: str,
) -> IndexFixtureManifest

capture_index_pages(
    cohort: InventoryCohort,
    *,
    fixture_id: str,
    paths: FixturePaths,
    broker: SecBroker,
    contribution: FixtureContribution,
) -> IndexCaptureResult

```

`capture_index_pages` fetches one page per `IndexWorkItem` through the supplied broker
and serializes all SQLite writes in the coordinator. `responses_added` and
`responses_reused` count successful fetched page cases according to whether their
URL+digest required a new response row or matched an existing row; a store hit does
not avoid that fetch. Failures do not
create `index_responses` or `index_cases` rows. Every `CohortObservation` is preserved
in `cohort_members`, including observations whose page request failed.
Replay requires an exact response key,
so an accession with multiple observed digests cannot silently select a version. The
reader opens SQLite read-only, verifies the schema, decompresses and verifies each
requested response, and returns the original uncompressed bytes. A whole-database
digest is optional and, if retained, is checked at most once per reader using streaming
hashing. One reader can replay multiple pages without re-hashing the whole database
for every case. The manifest is published atomically after the database transaction
commits and SQLite is checkpointed; compute a database digest only if the optional
digest policy is retained. Its database path is relative to the manifest directory.

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

`open_index_fixture` validates the committed manifest and schema, then serves exact
uncompressed bytes by accession and response key from its read-only connection. It
makes no network request and never reopens the source catalog plan. Each replay checks
the requested response digest. A database-wide digest is optional; see S7a's fixture
identity refinement. Wrong-schema and response-digest-mismatched data are refused.

## Tests

- URL+digest dedup: the same response keyed by URL and digest, never duplicated.
- Changed response appends: a new digest adds a row; the old row persists.
- Source-CIK/source-plan union: multiple cohort sources contribute one page.
- Exact uncompressed byte/hash round trip: replay returns the original body, not its
  stored zstd frame.
- Reader replays multiple cases read-only and verifies each decompressed response;
  optional database-digest verification does not materialize the whole SQLite file.
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
replay without HTTP through a reusable verified reader, unions source-CIK plan contributions without duplicating pages, refuses
wrong-schema databases, and pins the schema version in an atomic manifest. No source
evidence is ever overwritten.
