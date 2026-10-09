# `edgar_sec.pipelines.document_inventory`

## Purpose

Project filing-cohort observations into accession-level index-page work, capture
and replay `-index.html` responses, and build offline parser-review artifacts.
Layer 4 consumes published `filing_catalog` plans and imports downward only.

## Contracts

- Fixture capture reuses successful pages and records additional source membership; failed pages remain retryable. Replay validates the response digest and returns exact decompressed bytes. Inventory fixtures live at `{artifacts_root}/document_inventory/fixtures/<fixture_id>/`; their `manifest.json` uses the shared `foundation.runtime.fixtures` envelope, while `details` and the SQLite schema remain inventory-owned.
- Plan and fixture discovery reads manifests only; the operator selects discovered artifacts instead of accepting arbitrary plan JSON paths.
- `engine.index_pages.parser.parse_html_index` transforms explicit bytes to typed domain
  records without network or artifact access; unknown structure never becomes an empty
  successful parse.
- S4 work orders are sorted Parquet relations with validated identity; only one bounded chunk is read into worker memory at a time.
- The coordinator holds an exclusive run lock; completed accession results are journaled atomically and incomplete chunks resume from validated progress.
- SIGINT/SIGTERM stop new submissions, drain in-flight work, and leave incomplete chunk pointers unchanged.
- `run_missing_accessions` returns aggregate run counters and a bounded prefix of per-chunk details, rather than retaining one result object per work-order chunk.
- Snapshot candidate staging writes outcomes, entries, and source-CIK edges incrementally. The anti-join runs in resource-configured DuckDB and emits Parquet relations without collecting full accession keys in Python.
- The S5 projection validates a published catalog plan, writes normalized cohort relations, and pins a sorted pre-fetch work order before any SEC request.
- Durable publication pins the branch tip. `base_snapshot_id` selects the delta's lineage base and the S5/S4 identity; when omitted, the tip of the selected branch (default `main`) is used. An explicit base must match the branch tip, so historical bases require a branch created at that tip. `--expected-branch-tip` pins the branch pointer expected at commit; a concurrent move refuses publication without moving the pointer, and a retry re-anti-joins against the new parent.
- Persisted Run cancellation is recorded before the command returns; incomplete chunks,
  retryable outcomes, parser refusals, and cancellation block independent publication.

## Command surface

<!-- AUTOGEN:COMMANDS:START -->
| Subcommand | Description | Arguments |
| :--- | :--- | :--- |
| `dag` | Snapshot DAG operations | `[--root]`, `[--json]` |
| `distrib` | Distributed worker bundle lifecycle | `[--artifacts]` |
| `fixture` | create, fill, and list dataset fixtures | — |
| `project` | project a published catalog plan into a resumable run | `--catalog-plan`, `[--base-snapshot-id]`, `[--branch]`, `[--explicit-refresh]`, `[--chunk-size]`, `[--artifacts]`, `[--json]` |
| `publish` | publish a completed inventory run to a DAG branch | `--run-id`, `[--branch]`, `[--expected-branch-tip]`, `[--artifacts]`, `[--json]` |
| `query` | query active document inventory snapshots | `[--accession]`, `[--form]`, `[--filing-cik]`, `[--source-cik]`, `[--limit]`, `[--artifacts]`, `[--json]` |
| `review` | generate review artifacts and compare review runs | — |
| `run` | fetch and parse pending index pages | `--run-id`, `[--retry-failures]`, `[--workers]`, `[--confirm-stale-lock]`, `[--artifacts]`, `[--json]` |
| `status` | inspect projected inventory runs | `[--run-id]`, `[--artifacts]`, `[--json]` |
<!-- AUTOGEN:COMMANDS:END -->

### Usage examples

```bash
# Project a catalog plan into a resumable run
python run.py inventory project --catalog-plan plan-2024-01-15 --chunk-size 100

# Check run status
python run.py inventory status --run-id 2024-01-15T120000Z

# Run fetch and parse with multiple workers
python run.py inventory run --run-id 2024-01-15T120000Z --workers 8

# Publish completed run to snapshot
python run.py inventory publish --run-id 2024-01-15T120000Z --branch main

# Query inventory snapshots
python run.py inventory query --accession 0000320193-23-000004 --limit 10
```

## Artifact layout

<!-- AUTOGEN:PATHS:START -->
```text
{artifacts_root}/
├── document_inventory/
│   ├── fixtures/
│   │   └── {fixture_id}/
│   │       ├── index_fixtures.sqlite
│   │       └── manifest.json
│   ├── review-runs/
│   │   └── {review_id}/
│   │       └── manifest.jsonl
│   └── snapshots/  # Published snapshot root, owned by S5.
│       ├── {snapshot_id}/
│       ├── .publication.lock
│       └── catalog.sqlite  # SQLite DAG catalog database for published inventory snapshots.
├── runtime/
│   └── {socket_id}.sock
└── transient/
    └── document_inventory/
        ├── projection-staging/
        └── {run_id}/
            ├── chunks/
            │   └── {chunk_id}/
            │       ├── attempt-{attempt_id}/
            │       │   ├── entries.parquet
            │       │   ├── manifest.json
            │       │   └── outcomes.parquet
            │       ├── progress/
            │       │   ├── current.json
            │       │   └── progress-{attempt_id}.duckdb
            │       └── current.json
            ├── publication/  # S5-owned staging directory inside this run.
            ├── cancelled.json
            ├── cohort_accessions.parquet
            ├── cohort_sources.parquet
            ├── projection_manifest.json
            ├── run.lock
            ├── run_manifest.json
            └── work_order.parquet
```
<!-- AUTOGEN:PATHS:END -->

## Deliberate gaps

- The parser has not completed the historical SEC layout audit; final acceptance still
  depends on S0 evidence.
- `cohort.py` remains an in-memory projection for small fixture and review inputs; the
  production build uses the streamed catalog-plan projection in `snapshot/`.
- Refreshes hide prior entry rows from active snapshot queries through DAG scoped masking,
  but do not publish a direct mapping of superseded entry IDs.
