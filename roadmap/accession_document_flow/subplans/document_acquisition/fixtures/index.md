# `acquisition fixture`

## Purpose and status

Capture selected S9 parser-input bodies from a validated published S6 plan for offline
review. Schema v3 fixtures pin one target plan by ID, schema version, and digest. Earlier
fixture-store versions are rejected without migration.

## CLI and operator shape

```text
acquisition fixture create --fixture <id> --plan-id <published-s6-plan-id>
acquisition fixture fill --fixture <id> --allow-network [--limit <targets>]
acquisition fixture list [--fixture <id>]
acquisition review generate --fixture <id> [--output <review-dir>]
acquisition review compare --base <review-dir> --new <review-dir>
acquisition review analyze --run <review-dir> [--output <analysis-path>]
```

The shared inventory-style review console supports fixture create and plan-driven fill,
list, parser-review generation, compare, analyze, and `s` to switch the active S6 plan.
Create pins the selected plan. Fill requires live-network consent and captures executable
plan targets without projecting or running S9. A target limit bounds each fill; repeated
fills skip already stored target cases. Listing is deterministic and read-only.

## Capture contract

- Fill revalidates the fixture pin against the published plan and fetches selected parser
  inputs using the shared bounded, redirect-validated SEC transport.
- Inventory-selected targets follow their pinned URLs. An exact-form catalog-direct
  target without an inventory entry resolves through an accession index, stored and
  reused once per fixture/accession.
- Fixtures contain selected document bytes, plan metadata, and only the lazy-index bytes
  required to resolve the selected target. Ordinary source responses, bundle containers,
  and failed attempts are not retained.
- Capture/case/index metadata is append-only. Failed targets remain uncaptured and are
  reported by failure code for retry.

## Listing and internal body verification

Listing opens fixtures read-only and performs SQLite integrity and foreign-key checks. It
does not decompress or hash body BLOBs. Parser review verifies and materializes each
selected body and verifies each referenced lazy-index BLOB internally.

## Review console

Review generation invokes current acquisition-engine parser handlers on verified fixture
bytes and remains offline. It does not require an acquisition run, work order, processing
receipt, or prior S10 result. A review run contains a `manifest.jsonl`, per-case
`processing-review.json` artifacts, and parser outputs. Comparison validates both review
runs before computing the shared case-level diff. Offline analysis validates manifests and
output digests without accessing fixture BLOBs or making network requests.

## Detailed contracts

- [Fill fixture cases](fill.md)
- [List fixture evidence](list.md)
- [SQLite schema and BLOB lifecycle](storage.md)
