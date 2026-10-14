# `acquisition fixture list`

## Purpose and status

List validated parser fixtures and per-target body metadata without decompressing body BLOBs. Discovery is implemented in the fixture store and wired through the CLI and shared review console.

## CLI and operator

```text
acquisition fixture list [--fixture <id>] [--json]
```

Listing is read-only and requires no confirmation. Fixture summaries include the immutable S6 plan pin, run capture/case counts, and deterministic fixture order.

```python
def list_fixture_summaries(paths: AcquisitionPaths) -> Iterator[FixtureSummary]: ...

def list_fixture_cases(
    paths: AcquisitionPaths, *, fixture_id: str | None = None
) -> Iterator[FixtureCaseMetadata]: ...
```

## Read-only contract

- Validate fixture ID, schema version/layout, SQLite integrity and foreign keys, immutability triggers, and equality between manifest/database plan pins.
- Discover fixtures, captures, and cases in stable sorted order.
- Case metadata includes run/capture/plan and target/attempt identity, parser routing facts, and selected-body digest/size.
- Open fixture databases read-only. Listing does not select, decompress, or hash body BLOBs.
- Listing creates no fixture, changes no database, and makes zero HTTP requests.

## Tests

Offline tests cover discovery order, run-scoped counts, schema validation, and read-only access. BLOB bodies are not materialized by listing.
