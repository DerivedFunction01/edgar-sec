# `acquisition fixture list`

## Purpose and status

List validated fixture IDs and per-target evidence metadata without loading document
bodies. Fixture discovery and case iteration are implemented in the store discovery
API and wired through the CLI and operator.

## CLI and operator

```text
acquisition fixture list [--fixture-id <id>] [--capture-id <id>] [--target-id <id>] [--json]
```

Each filter is optional. The operator presents the same optional fixture, capture, and
target filters. Listing is read-only and requires no confirmation.

```python
def list_fixtures(paths: AcquisitionPaths) -> Iterator[str]: ...

def list_fixture_cases(
    paths: AcquisitionPaths,
    *,
    fixture_id: str | None = None,
    capture_id: str | None = None,
    target_id: str | None = None,
) -> Iterator[FixtureCaseMetadata]: ...
```

## Read-only contract

- Validate fixture IDs, manifest envelope, schema version/layout, SQLite integrity,
  foreign keys, and immutability triggers. Invalid fixtures are reported rather than
  silently skipped.
- Stream fixture IDs and matching case metadata in deterministic order. Case metadata
  includes capture/run/plan and target/attempt identity, outcome, error, retrieval
  details, and recorded source/selected digests and sizes.
- Open each fixture database read-only. Listing does not select, decompress, or hash
  response BLOBs; SQLite integrity and foreign-key checks still run when a store opens.
  Full response-body verification belongs to replay.
- Fixture, capture, and target filters are bound exact-value filters. Metadata-only
  failures remain visible with absent body digest/size fields rather than appearing as
  empty response bodies.
- Listing creates no fixture, changes no database, and makes zero HTTP requests.

## Tests

Offline tests cover discovery order, filters, metadata-only cases, schema validation,
and read-only access. BLOB bodies are not materialized by listing.
