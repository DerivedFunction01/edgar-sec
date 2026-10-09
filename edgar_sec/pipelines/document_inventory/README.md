# `edgar_sec.pipelines.document_inventory`

## Purpose

Project filing-cohort observations into accession-level index-page work, capture
and replay `-index.html` responses, and build offline parser-review artifacts.
Layer 4 consumes published `filing_catalog` plans and imports downward only.

## Module layout

| Module | Responsibility |
|---|---|
| `cohort.py` | Validate catalog observations and project selected cohorts into accession work. |
| `discovery.py` | Manifest-only discovery and selection of published plans and fixtures. |
| `fixture_store/` | Mutable local response capture, provenance, discovery, and exact-byte replay; see its [package contract](fixture_store/README.md). |
| `review_artifacts/` | Offline parser review output with inert HTML and deterministic manifests; see its [package contract](review_artifacts/README.md). |
| `snapshot/` | Snapshot schemas, streamed catalog-plan projection, bounded DuckDB anti-join, and publication primitives; see its [package contract](snapshot/README.md). |
| `schemas.py` | Public access to the snapshot-owned relation schemas and merge specifications. |
| `paths.py` | Inventory-specific artifact, runtime, and transient paths; binds index fixtures to the shared foundation resolver. |
| `run_manifest.py` | Path-backed work-order identity and chunk manifest validation. |
| `run_state.py` | Read-only projection validation, run discovery, and persisted execution status. |
| `checkpoint.py` | Transient outcome/entry schemas, attempt commit markers, and resume validation. |
| `progress.py` | Per-accession DuckDB transactions and resumable chunk progress. |
| `run_lock.py` | Exclusive run ownership and explicit stale-lock recovery. |
| `broker.py` | Picklable client for the shared SEC broker and typed fetch results. |
| `worker.py` | Per-accession worker task and typed failures. |
| `coordinator.py` | Resource-capped scheduling, cancellation, chunk commit, resume, and retry. |
| `distribution_adapter.py` | Adapts document inventory to the generic Layer 2 distribution engine. |
| `review_adapter.py` | Adapts document inventory to the generic Layer 2 review/fixture harness. |
| `cli.py` | Command dispatch, argument parsing, and subparser definitions. |
| [commands/](commands/README.md) | Project, run, status, publish, query, fixture, and review commands. |
| `operator.py` | Discovery-driven interactive operations. |
| `run.py` (repository root) | Dispatches the inventory entry to its operator. |

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

## Public surface

`schemas.py` is the permitted cross-pipeline contract for canonical inventory relation
schemas and DAG specifications; their definitions remain owned by `snapshot/`.

## Command surface

The approved lifecycle commands are `inventory project`, `inventory run`,
`inventory status`, and `inventory publish`. Project pins the selected branch tip
as the run base; Run performs SEC requests; Status is read-only; Publish makes no
network requests and refuses unless the selected branch still points at the run's
pinned base. Direct CLI Run is explicit network intent; the interactive Run action
requires default-no confirmation. The Snapshot DAG Publish action selects and
publishes an existing run.

```text
python run.py inventory project --catalog-plan PLAN
                    [--base-snapshot-id ID] [--branch <name>]
                    [--chunk-size N] [--explicit-refresh]
python run.py inventory run --run-id ID [--workers N] [--retry-failures]
                    [--confirm-stale-lock]
python run.py inventory status [--run-id ID] [--json]
python run.py inventory publish --run-id ID [--branch <name>]
                    [--expected-branch-tip ID]
python run.py inventory query [--accession ACC] [--form FORM] [--filing-cik CIK] [--source-cik CIK]
python run.py inventory fixture create --fixture ID --catalog-plan PLAN [--limit N]
python run.py inventory fixture fill --fixture ID --catalog-plan PLAN [--limit N]
python run.py inventory fixture list
python run.py inventory review generate --fixture ID [--output DIR] [--accession ACCESSION]
python run.py inventory review compare --base DIR --new DIR [--output DIR]
python run.py inventory distrib export --plan-id PLAN --workers N [--destination DIR]
python run.py inventory distrib worker --bundle DIR
python run.py inventory distrib import --bundle DIR
```

Project reports accession and work-order counts and its configured chunk size. Status
reports pending accessions and chunks, committed chunks, retryable/refused outcomes,
and lock owner metadata; it does not repair partial runs. Commands accept `--artifacts`
and `--json`; capture also accepts `--limit`, and review
accepts `--workers`, `--limit`, and repeatable `--accession`. Running `python run.py
inventory` opens the discovery-driven operator menu. Its approved root actions preserve
`1` Query, `d` Distribution, `p` Snapshot DAG, `f` Fixtures/review, and `0` Exit, and
add `2` Project, `3` Status, and `4` Run.

## Mirrored tests

`tests/pipelines/document_inventory/`: cohort, fixture store, review artifacts, snapshot,
broker, worker, coordinator, run lock, progress journal, paths, run-manifest, checkpoint, discovery, operator, and CLI tests. Parser tests live in
`tests/engine/index_pages/`; shared contract tests live in `tests/domain/document_inventory/`.

## Deliberate gaps

- The parser has not completed the historical SEC layout audit; final acceptance still
  depends on S0 evidence.
- `cohort.py` remains an in-memory projection for small fixture and review inputs; the
  production build uses the streamed catalog-plan projection in `snapshot/`.
- Refreshes hide prior entry rows from active snapshot queries through DAG scoped masking,
  but do not publish a direct mapping of superseded entry IDs.
