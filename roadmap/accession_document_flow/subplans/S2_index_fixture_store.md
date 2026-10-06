# S2 — Index-Page Fixture Capture and Replay Store

## Owner and status

- Owning stage in [implementation.md](../implementation.md): **S2**.
- Status: schema and fixture manifest design before or alongside the HTML parser;
  may be implemented before S3 because it stores bytes and source metadata only.
- Depends on: the cohort adapter (S1) for accession URLs.
- Non-blocking: S3 parser (the store holds bytes; the parser consumes parsed rows).

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

## Fixture manifest

An atomic manifest pinned at commit records the SQLite schema version, fixture ID,
contributing cohort sources, page and accession counts, and the database-relative path.
`foreign_keys` is enabled so SQLite enforces referential integrity.

## Capture and fill operation

1. Project the cohort with the S1 adapter.
2. Acquire each response through one brokered SEC transport. A worker fetches through
   `SecBrokerClient`, hashes the response, and the coordinator appends a new row.
3. A response whose URL+digest exists is reused; a changed response appends a new row
   keyed by `(request_url, response_sha256)`. Transport failures are recorded as run
   results, not response rows.
4. Write `index_cases` linking each accession to its immutable response key and `cohort
   members` for source relationships.

The store never mutates source evidence. Re-fetching a changed response appends; no row
is overwritten.

## Read-only replay

Replay loads the committed database, resolves cases by accession, and serves the
compressed body to a chosen parser version. It makes no network request. Selected cases
and the fixture ID drive reproducibility. Wrong-schema databases are refused.

## Tests

- URL+digest dedup: the same response keyed by URL and digest, never duplicated.
- Changed response appends: a new digest adds a row; the old row persists.
- Co-filer/source-plan union: multiple cohort sources contribute one page.
- Exact byte/hash round trip: stored bytes reproduce the captured digest.
- Read-only non-mutation: replay opens the database read-only and never alters it.
- Wrong-schema refusal: a mismatched schema version is rejected before replay.
- Atomic manifest-after-commit: the manifest reflects a committed database.
- Replay without HTTP: replay resolves cases solely from the fixture store.
- Deterministic case ordering: replay returns cases in a stable order.

## Committed inputs

Commit only the sanitized representative page cases and the audit's small portable
result table. Use local generated databases for the full survey corpus; they live under
a transient path and are not tracked.

## Acceptance criteria

The fixture store is append-only with a URL+digest primary key, supports exact-byte
replay without HTTP, unions co-filer source plans without duplicating pages, refuses
wrong-schema databases, and pins the schema version in an atomic manifest. No source
evidence is ever overwritten.
