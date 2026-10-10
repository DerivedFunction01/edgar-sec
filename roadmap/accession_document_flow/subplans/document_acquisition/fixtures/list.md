# `acquisition fixture list`

## Purpose and status

List fixture IDs, captures, and per-target evidence metadata without loading document
bodies. This is design-only; the S9 fixture index is not implemented.

## UX and signature

The operator lists fixture IDs and case counts, then may inspect one fixture's
captures. The CLI supports all fixtures or an explicit ID and emits the same summary
as sorted JSON when requested.

```python
def list_fixtures(
    fixture_id: str | None,
    *,
    paths: AcquisitionPaths,
) -> tuple[FixtureSummary, ...]: ...

def list_fixture_cases(
    fixture_id: str,
    *,
    capture_id: str | None = None,
    target_id: str | None = None,
    paths: AcquisitionPaths,
) -> tuple[FixtureCaseSummary, ...]: ...

def cmd_fixture_list(args: argparse.Namespace) -> int: ...
```

## Read-only contract

- Validate fixture IDs, database `user_version`, schema, and metadata path containment.
  An invalid fixture is reported with an error code and is not silently skipped.
- Show capture ID, run/plan identity, target/attempt identity, source origin,
  retrieval mode, outcome, error code, source/selected digests and byte sizes, and
  whether the source BLOB is present in the index.
- Do not read or hash every body during listing. Replay performs full streaming
  verification against the recorded digest and size.
- Use `LEFT JOIN`/bound filters so metadata-only failures remain visible. A missing
  BLOB is presented as corrupt/missing evidence, not as an empty document.
- Listing creates no fixture directory, migrates no schema, changes no database, and
  makes zero HTTP requests.

## Tests

Tests cover empty and populated fixtures, filters, metadata-only cases, missing BLOB
reporting, corrupt indexes, unknown schema versions, path escapes, and read-only
database behavior. Listing does not read large BLOB values.
