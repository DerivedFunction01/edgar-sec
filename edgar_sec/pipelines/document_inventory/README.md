# `edgar_sec.pipelines.document_inventory`

## Purpose

Project filing-cohort observations into accession-level index-page work, capture and
replay `-index.html` responses without the network, fetch and parse missing index pages
through the shared SEC broker, and (in later stages) publish an immutable, queryable
inventory snapshot. Layer 4: consumes published artifacts from `filing_catalog`; imports
only foundation, infra, domain, and sibling modules.

## Module layout

| Module | Responsibility |
|---|---|
| `cohort.py` | Read and validate catalog observations, then project one `IndexWorkItem` per accession. Shared records live in `domain/document_inventory`. |
| `fixture_store.py` | Append-only capture-and-replay store (`index_fixtures.sqlite` + manifest): create, capture, publish, list, replay. |
| `paths.py` | Validated inventory run/chunk/attempt path methods over `ProjectPaths.artifacts_root` and the shared transient/pointer helpers. |
| `run_manifest.py` | Atomic run manifest pinning resume identity (parent snapshot, cohort, parser/schema versions, chunk size, work-order version) and deterministic chunk partitioning. |
| `checkpoint.py` | Transient outcome schema/status, staged attempt writers, attempt manifests, the chunk pointer commit marker, and resume validation. |
| `broker.py` | Picklable client for the shared SEC broker and typed fetch results. |
| `worker.py` | Module-level per-accession task and typed worker failures. |
| `coordinator.py` | Bounded in-flight scheduling, chunk commit, resume, and explicit retry. |
| `cli.py` | Command surface (`inventory` subcommands plus interactive menu). |

## Contracts

- `project_cohort` emits one work item per accession, keyed by canonical accession; the cohort reader is offline and deterministic from a catalog snapshot or committed fixture.
- `capture_index_pages` upserts pages by `(request_url, response_sha256)`; changed responses append, failures become typed capture failures, and every source observation is recorded in `cohort_members`.
- `publish_index_fixture` finalizes the manifest with the committed database digest; `replay_index_page` opens the store read-only and refuses mismatched schema or digests.
- `engine.index_pages.parser.parse_html_index` transforms explicit bytes to typed domain
  records without network or artifact access; unknown structure never becomes an empty
  successful parse.
- The run manifest is written or exactly matched before the first broker request; any identity, version, chunk-size, or worklist mismatch refuses the run.
- Chunk ids derive from work-order version and sorted membership, never completion order. An attempt commits as: write both Parquet files → validate schemas, counts, membership, digests → write `manifest.json` → atomically advance `current.json`. The pointer is the commit marker; orphan attempts are ignored on resume.
- `outcomes.parquet` holds exactly one typed row per accession (including recognized-empty and failed outcomes); `entries.parquet` preserves every parsed `InventoryEntry` row. Fetch/worker failures are retryable via `retry_failures=True`, which carries successful and parser-refusal outcomes forward and rewrites only the failed accessions; parser refusals (`unrecognized`, `parse_failure`) are never retried.
- `run_missing_accessions` starts one broker per run, derives its pool from `derive_resources().workers`, streams bounded per-chunk batches through spawn-context tasks, and never crosses production IPC with raw page bytes.

## Command surface

```
python run.py inventory <subcommand> [options]
  cohort        build the inventory cohort from a source
  index list    list captured index pages
  index replay  replay a captured index page
  status        report the inventory snapshot
  query         query the snapshot
  publish       publish the inventory snapshot
```

Common options: `--artifacts`, `--workers`, `--limit`, `--json`. Invoked without a
subcommand from `python run.py inventory` (no arguments), the launcher opens a narrow
interactive menu. Exit codes: 0 success, 1 error, 2 invalid usage, 130 interrupt.

## Mirrored tests

`tests/pipelines/document_inventory/`: cohort, fixture store, broker, worker, coordinator,
paths, run-manifest, checkpoint, and CLI tests. Parser tests live in
`tests/engine/index_pages/`; shared contract tests live in `tests/domain/document_inventory/`.

## Deliberate gaps

- The engine parser's first structural pass is implemented against the standard
  filing-page fixture; final era/table rules await S0's empirical audit.
- The CLI command bodies are placeholders; `inventory <subcommand>` returns 1 until
  the owning stage is implemented. The S4 coordinator is a library entry point
  (`coordinator.run_missing_accessions`); the `inventory build` command that drives it
  end-to-end needs S5's anti-join and publication, which S7a/S12 own.
- `--workers`/`--limit` are accepted but unused by the CLI until `inventory build` lands.
- S5 snapshot publication and S6 target planning are out of scope for this phase.
