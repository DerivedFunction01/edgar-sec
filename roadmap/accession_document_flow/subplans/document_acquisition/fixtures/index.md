# `acquisition fixture`

## Purpose and status

Capture selected S9 parser-input bodies for offline review. New schema v2 fixtures pin one validated published S6 target plan by ID, schema version, and digest. Schema v1 response-group fixtures are rejected; no migration, old-schema reader, alias, or dual-version path exists.

## CLI and operator shape

```text
acquisition fixture create --fixture <id> --plan-id <published-s6-plan-id>
acquisition fixture fill --fixture <id> --run-id <run-id>
acquisition fixture list [--fixture <id>]
acquisition review generate --fixture <id> [--output <review-dir>]
acquisition review compare --base <review-dir> --new <review-dir>
acquisition review analyze --run <review-dir> [--output <analysis-path>]
```

The shared inventory-style review console supports fixture create, run fill, list,
parser-review generation, compare, analyze, and `s` to switch the active S6 plan. Fixture
and run choices are discovered and paginated. Fill captures all acquired selected staged
bodies from the selected run; the operator never enters target, attempt, capture, or body
digest values. Listing is deterministic and read-only.

## Capture contract

- Fill validates the fixture pin, run manifest/work order, acquired target state, and selected-body handoff. It makes no SEC request and does not require raw response-evidence retention.
- Only acquired targets with verified selected staged bodies are captured. Non-executable and non-acquired targets are skipped; missing, corrupt, or oversized staged bodies refuse the fill.
- Fixtures contain selected document bytes and parsing metadata, not raw HTTP responses, lazy-index pages, bundle containers, or failed attempts.
- One deterministic capture groups the selected bodies from a run. Capture and case records are immutable; repeated fill is idempotent for the same run/body set.
- Body BLOBs are streamed into Zstandard-compressed SQLite storage and verified before atomic append. The configured body-size cap is shared with acquisition settings.

## Listing and internal body verification

Listing opens fixtures read-only and performs SQLite integrity and foreign-key checks. It does not decompress or hash body BLOBs. Parser review verifies and materializes each selected body internally; it does not export fixture bytes or mutate fixture evidence.

## Review console

Review generation invokes current acquisition-engine parser handlers on verified fixture bytes. It does not need the source run's processing results, receipts, or work order and remains offline. A review run contains a `manifest.jsonl`, per-case `processing-review.json` artifacts, and parser outputs. Comparison validates both review runs before computing the shared case-level diff. Offline analysis validates manifests and output digests, reports parser statuses and handler results, and never accesses fixture BLOBs. Analysis writes a separate report only when `--output` is supplied.

## Detailed contracts

- [Fill fixture cases](fill.md)
- [List fixture evidence](list.md)
- [SQLite schema and BLOB lifecycle](storage.md)
