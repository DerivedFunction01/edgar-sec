# `edgar_sec/pipelines` — Layer 4: orchestration, command surfaces, and publication

This layer owns the parts of the system that *sequence* work: the CLI and
interactive operator, the deterministic plan, the resumable worker, and the
coordinator that decides when a dataset may be published. It is not a place for
normalization, transport, or storage primitives — every one of those is decided
in a lower layer and consumed here.

## Purpose

Three pipelines, each a complete vertical from a published input to a published
output:

- `metadata_sync/` — Phase 1, feature-complete with documented scope reductions.
  Ingests EDGAR submissions metadata for a fingerprinted CIK manifest, chunks it,
  writes resumable Parquet checkpoints, and publishes a sorted
  `metadata.parquet` snapshot. It also captures immutable external source
  snapshots and projects the curated input against them (`sources refresh`,
  `sources compare`). Retired relative to v1: persisted project configuration,
  a merge-only snapshot rename, the two-stage partition merge, and a `preview`
  subcommand — see that package's README for each decision and its reason.
- `filing_catalog/` — Phase 2, complete. Zero network. Materializes a catalog
  snapshot from a Phase 1 snapshot and publishes immutable, content-addressed
  target plans for the next phase to consume.
- `document_storage/` — Phase 2.5, implemented with M6.3/M6.4 deferred. Fetches
  primary filings, unrolls SGML, normalizes, resolves delegated exhibits, and
  consolidates per-run snapshots into one canonical snapshot across runs.

The unifying rule is that **Layer 4 is the only layer permitted to
orchestrate.** Orchestration means ordering, chunking, checkpointing,
validating, and publishing — deciding *what happens next*. Lower layers expose
capabilities; a layer-4 module sequences them into a run.

The unifying rule of publication is that **nothing is published by a worker.**
Workers emit immutable, schema-versioned fragments into a transient tree; a
coordinator validates identity, provenance, schema, and duplicates, and only
then writes into the published tree and advances the `current` pointer. This is
the Phase 1 contract in AGENTS.md §4, and all three pipelines hold it, though
only `metadata_sync` and `document_storage` have workers at all.

## Layer map

Layer 4 is the top of the graph. Nothing may import it.

```text
Layer 4  pipelines/            <-- this package
              |  may import engine, infra, domain, foundation
              |  ORCHESTRATION IS ALLOWED ONLY HERE
Layer 3  engine/               Unroller, Profile, Normalizer, Arrow Builder,
                               selection features / policy / selector
              |  may import infra, domain, foundation
Layer 2  infra/                sec_http, broker, storage (atomic, parquet,
                               duckdb, document parts, manifests, payload store)
              |  may import domain, foundation ONLY
Layer 1  domain/               Cik, AccessionNumber, submissions schemas,
                               document models, filing-catalog schemas
              |  may import foundation
Layer 0  foundation/           hashing, serialization, env, paths, resources,
                               memory, settings, progress, interactive, scanners
```

**Layer 4 may import from `engine`, `infra`, `domain`, and `foundation` —
downward only.** This is not a convention. The `layer-boundary` scanner
(`foundation/scanners/layers.py`) parses each module's AST on every `check.py`
run and reports any import whose callee layer ranks strictly above the caller's;
`pipelines` is rank 4 in `_LAYER_RANK` (`layers.py:11-17`), and `_check_import`
raises the finding when `callee_rank > caller_rank` (`layers.py:86-99`). Nothing
ranks above 4, so no upward import out of this layer is expressible.

Same-layer imports are unrestricted, which is why `filing_catalog/catalog_job.py`
imports `metadata_sync/paths.py` and `filing_catalog/cli.py` imports six
sibling modules. The scanner compares layer ranks only, so two `pipelines`
modules importing each other would pass; intra-package cycles are not detected.

Verified compliance as the tree stands. Every `edgar_sec.*` import across the
layer crosses downward to one of the three lower layers or stays inside
`pipelines`:

| Imported package | Modules that import it |
| :--- | :--- |
| `edgar_sec.foundation` | all three pipelines — `hashing`, `serialization`, `runtime.{memory,paths,resources,progress,interactive}`, `runtime.settings` |
| `edgar_sec.domain` | `metadata_sync` (`identity`, `sec_urls`, `submissions.schemas`); `filing_catalog` (`filing_catalog.{filters,schemas}`, `submissions.schemas`); `document_storage` (`document.{acquisition,models}`, `forms.decisions`, `identity`, `sec_urls`) |
| `edgar_sec.engine` | `metadata_sync` (`submissions.builder`); `filing_catalog` (`selection.{features,policy,selector}`); `document_storage` (`document.{page_markers,unpacker}`, `forms.normalize`, `forms.plugins.registry`) |
| `edgar_sec.infra` | `metadata_sync` (`sec_http.{client,errors}`, `storage.{atomic,duckdb,parquet}`); `filing_catalog` (`storage.{atomic,duckdb,duckdb_catalog,parquet}`); `document_storage` (`broker.sec_broker`, `sec_http`, `storage.{document_parquet,document_parts,duckdb,manifests,parquet,payload_store}`) |
| same-layer `edgar_sec.pipelines` | `filing_catalog/catalog_job.py` (`metadata_sync.paths`); every pipeline's `cli.py` imports its own siblings |

Two `engine` dependencies are worth calling out because they are what put this
package in Layer 4 rather than Layer 2. `document_storage` fetchers call
`engine.document.unpacker` to select a sub-document out of an SGML envelope, and
`metadata_sync` workers call `engine.submissions.builder` to turn normalized
dict rows into an Arrow table. A module that needs the engine cannot live below
it — `document_storage/__init__.py:3-6` states this as the reason the package
sits at Layer 4.

## Layout

| Module | Responsibility |
| :--- | :--- |
| `__init__.py` | Docstring only (1 loc). No re-exports, per AGENTS.md §1.2. |
| `metadata_sync/__init__.py` | Docstring only (1 loc). |
| `metadata_sync/cli.py` | The five pipeline commands, the nested `sources` group, and the argparse surface; each `cmd_*` is a plain callable the operator also calls (372 loc). |
| `metadata_sync/operator.py` | Interactive wizard; a presentation shim over the same `cmd_*` functions (146 loc). |
| `metadata_sync/planner.py` | Deterministic chunk/partition planning, `plan.json` write, partition-coverage invariant, and stale-plan/schema-version rejection (195 loc). |
| `metadata_sync/manifest.py` | CIK CSV ingestion, normalization, deduplication, curated names, and the input fingerprint (110 loc). |
| `metadata_sync/worker.py` | Resumable chunk and partition execution over a thread pool; the never-refetch guarantee (268 loc). |
| `metadata_sync/checkpoints.py` | What counts as a *complete* chunk on disk (133 loc). |
| `metadata_sync/merger.py` | Coordinator validation, out-of-core sorted merge, progress events, snapshot manifest, pointer (278 loc). |
| `metadata_sync/augmentation.py` | Delta merge onto a published snapshot without refetching the base (234 loc). |
| `metadata_sync/sec_client.py` | One CIK to its submissions document plus every historical file it lists (120 loc). |
| `metadata_sync/paths.py` | `MetadataPaths` / `RunPaths`; the published-vs-transient split plus source and registry locations (148 loc). |
| `metadata_sync/source_registry.py` | Write-once, content-addressed `company_tickers.json` snapshots, reached by `sources refresh` (215 loc). |
| `metadata_sync/registry.py` | Curated-versus-source comparison and the effective-input projection, reached by `sources compare` (348 loc). |
| `metadata_sync/smoke_test.py` | Credential-gated live check that never publishes; replaces v1's `preview` command (141 loc). |
| `filing_catalog/__init__.py` | Docstring only (1 loc). |
| `filing_catalog/cli.py` | The four commands, policy resolution, and the stdout/stderr split (231 loc). |
| `filing_catalog/operator.py` | Interactive wizard over `cmd_materialize` / `cmd_plan` / `cmd_status` (83 loc). |
| `filing_catalog/catalog_job.py` | `materialize()`: one Phase 1 snapshot in, one immutable catalog out (316 loc). |
| `filing_catalog/planner.py` | `plan()` (four filters, 8 columns) and `plan_policy()` (quota profile, 18 columns) (562 loc). |
| `filing_catalog/expansion.py` | Parent validation, child derivation, and the 100%-retention invariant (352 loc). |
| `filing_catalog/publication.py` | Content-addressed plan ids, staged bundles, and the reuse-or-conflict policy (192 loc). |
| `filing_catalog/discovery.py` | Manifest-only catalog/plan/policy enumeration and `current` resolution (258 loc). |
| `filing_catalog/paths.py` | `FilingCatalogPaths` and the artifact-name constants (189 loc). |
| `document_storage/__init__.py` | Docstring only (7 loc); states the Layer 4 placement rationale. |
| `document_storage/cli.py` | `run` / `status` / `review` and plan-file ingestion (231 loc). |
| `document_storage/operator.py` | `run_document_storage()`: process chunks, resolve delegations, publish (328 loc). |
| `document_storage/worker.py` | Chunk processing, the process pool, and the checkpoint-reuse rule (498 loc). |
| `document_storage/fetching.py` | `ArchiveFetcher` protocol and the fixture / broker / live backends (442 loc). |
| `document_storage/processor.py` | `FilingProcessor`, `PassThroughProcessor`, and the processor fingerprint (231 loc). |
| `document_storage/delegation.py` | The exhibit second pass for stub primaries (282 loc). |
| `document_storage/merger.py` | Per-run snapshot publication: assemble, split into parts, write manifest, move pointer (403 loc). |
| `document_storage/vacuum.py` | `vacuum_snapshots()`: cross-run consolidation into one canonical snapshot (564 loc). |
| `document_storage/queries.py` | The direct SQL for consolidation; the only module that holds it (263 loc). |
| `document_storage/review.py` | `render_review_set()`: stratified, diffable review bundles (332 loc). |

Total 7,923 lines across 34 files: 31 modules plus three one-line `__init__.py`
docstrings. Per package: `metadata_sync` 2,157; `filing_catalog` 2,184;
`document_storage` 3,581.

## Contracts

**Guarantees this layer makes to its callers**

- `plan` is deterministic and performs **no network and no model calls.**
  `metadata_sync/planner.py:1-7` and `filing_catalog/planner.py` both derive an
  identity from the plan-defining inputs rather than a timestamp, so replanning
  an unchanged input is idempotent while changing the chunking produces a
  distinct plan.
- A worker never writes the canonical dataset. Every worker writes an immutable,
  schema-versioned fragment under a transient root; only a coordinator publishes.
  `metadata_sync/paths.py:1-6` names the split explicitly ("chunks are
  resumability state, snapshots are output"), and `filing_catalog/paths.py:8-12`
  gives the same shape.
- A partial file is never treated as complete. `metadata_sync/checkpoints.py:1-6`
  requires existence, canonical schema, exactly the planned CIKs, and the
  expected input fingerprint before a chunk counts; `document_storage/worker.py:109-130`
  additionally requires a matching processor fingerprint.
- Every DuckDB connection is bounded. All three pipelines call
  `infra.storage.duckdb.connect()` and never a raw `duckdb.connect()`;
  `connect()` sets `threads`, `memory_limit`, `temp_directory`, and
  `preserve_insertion_order=false` from `derive_resources()`
  (`infra/storage/duckdb.py:30-60`). Hardcoding them is blocked by the
  `resource-allocation` scanner, whose `_CANDIDATE_RE` matches
  `threads=`/`max_workers=`/`memory_limit=` literals and whose `_ALLOWED_PATHS`
  exempts only `foundation/runtime/resources.py`, `runtime/settings/`,
  `scanners/`, `scratch/`, and tests.
- Workers are sized from cgroup-aware memory, never from raw CPU count.
  `metadata_sync/worker.py:43-49` uses `derive_resources().workers`;
  `document_storage/worker.py:360-373` calls
  `auto_worker_count(resolved.available_memory_bytes, worker_memory_mib=512,
  safety_fraction=0.9)`. `filing_catalog` has no worker: the planner is
  single-connection and batched.
- Heap is reclaimed at bounded intervals. `reclaim()` (`gc.collect()` plus
  `malloc_trim(0)`) is called every `RECLAIM_INTERVAL = 64` documents in
  `metadata_sync/worker.py:146-149` and every 64 documents in
  `document_storage/worker.py:241-242` and after every completed future
  (`worker.py:462`), and after every batch in
  `document_storage/vacuum.py:250, 292, 379` and
  `filing_catalog/catalog_job.py:234, 262`.
- Settings are declared once, centrally. No pipeline in this layer defines a
  settings registry, a spec dataclass, or a dotted-path table of its own. Phase 2
  reads `catalog.source_batch_size` and `catalog.row_group_size` through
  `resolve_settings()` (`catalog_job.py:166-178`), which are declared in
  `foundation/runtime/settings/catalog.py`; Phase 1 and Phase 2.5 read
  `resolve_runtime_settings().sec` and take worker counts as explicit
  `int | None` arguments that default to machine-derived.
- The `current` pointer is written only after the artifact it names exists.
  `document_storage/merger.py:1-12` states the ordering and the reason: a
  pointer naming a missing dataset is worse than a stale one.
- A published artifact is immutable. `metadata_sync` refuses a stale plan
  (`planner.py:117-156`), `filing_catalog` refuses to overwrite an existing
  snapshot directory (`catalog_job.py:206-210`) and refuses to rewrite an
  incomplete or diverging plan bundle (`publication.py:104-134`), and
  `document_storage` refuses to republish an existing snapshot id
  (`merger.py:306-311`) and refuses a re-derived vacuum id before writing
  anything (`vacuum.py:472-480`).

**Obligations callers place on this layer**

- Run every command from the repository root. `resolve_paths()` treats the
  working directory as the project root and hard-errors if it is inside the
  `edgar_sec` package (`foundation/runtime/paths.py:141-162`), but running from
  any other subdirectory silently derives a second `.artifacts/` tree.
- Do not treat a chunk checkpoint as a dataset. Nothing in this layer exposes a
  transient path as a published one; `status` commands report published state
  only.
- Do not add a fourth pipeline without updating `run.py`'s `ENTRIES` tuple, the
  `layer-boundary` layer map in AGENTS.md §1, and the repository README's layout
  section. `run.py` is the single dispatcher and it holds the list explicitly.
- Do not have a worker construct a published path. The coordinator is the only
  writer of published artifacts, and `artifact-paths` blocks `.artifacts`
  literals outside the path resolvers in `foundation/runtime/paths.py` and the
  per-pipeline `paths.py` modules.

## Public surface

This layer publishes no re-exports: every `__init__.py` is a docstring, and
consumers import from the leaf module (AGENTS.md §1.2). The surface below is the
entry points, grouped by pipeline.

- `PipelineEntry`, `ENTRIES`, `main` — the root dispatcher registry and its
  three pipeline ids. `run.py` (repository root, not in this package).
- `operator_entrypoint`, `MenuAction`, `prompt_text` — the shared operator
  policy: menu with no arguments, CLI otherwise. `foundation/runtime/interactive.py`.
- `main`, `build_parser`, `cmd_plan`, `cmd_status`, `cmd_run`, `cmd_merge`,
  `cmd_augment`, `RunOptions` — Phase 1 command surface.
  `metadata_sync/cli.py`.
- `build_operator_menu` — the five-item Phase 1 wizard.
  `metadata_sync/operator.py`.
- `build_plan`, `derive_plan_id`, `load_plan`, `write_plan`, `plan_chunk_ids`,
  `PLAN_FORMAT_VERSION` — Phase 1 planning. `metadata_sync/planner.py`.
- `read_cik_manifest`, `InputManifest` — CIK CSV ingestion and the input
  fingerprint. `metadata_sync/manifest.py`.
- `run_chunk`, `run_partition`, `resolve_workers`, `normalize_one_cik`,
  `ChunkResult` — Phase 1 execution. `metadata_sync/worker.py`.
- `discover_completed_chunks`, `inspect_chunk`, `schema_matches`, `ChunkInfo` —
  what counts as complete. `metadata_sync/checkpoints.py`.
- `merge_chunks`, `publish_snapshot`, `validate_chunks`, `MergeReport`,
  `MergeError` — Phase 1 coordination. `metadata_sync/merger.py`.
- `augment`, `augment_from_manifest`, `plan_delta`, `base_snapshot_ciks`,
  `AugmentResult` — delta augmentation. `metadata_sync/augmentation.py`.
- `SubmissionsClient`, `CikFetchResult` — the fan-out to historical files.
  `metadata_sync/sec_client.py`.
- `refresh_company_tickers`, `load_source_snapshot`, `parse_company_tickers`,
  `source_snapshot_id`, `SourceSnapshot`, `SourceRegistryError`,
  `SOURCE_NAME`, `SOURCE_URL`. `metadata_sync/source_registry.py`.
- `MetadataPaths`, `RunPaths`, `resolve_metadata_paths`, `resolve_run_paths`.
  `metadata_sync/paths.py`.
- `main` of `smoke_test` — the bounded live check.
  `metadata_sync/smoke_test.py`.
- `main`, `build_parser`, `cmd_materialize`, `cmd_plan`, `cmd_expand`,
  `cmd_status` — Phase 2 command surface. `filing_catalog/cli.py`.
- `materialize`, `resolve_source`, `CatalogError`, `FALLBACK_POLICY_VERSION`,
  `TRANSIENT_SOURCE_PARTS`. `filing_catalog/catalog_job.py`.
- `plan`, `plan_policy`, `SCOPE_DETERMINISTIC`, `SCOPE_POLICY` — the two planning
  scopes. `filing_catalog/planner.py`.
- `expand`, `prepare_parent`, `validate_parent`, `validate_target`,
  `plan_fingerprint`, `plan_locator_keys`, `read_expansion_metadata`,
  `ExpansionLineage`, `ParentPlanError`. `filing_catalog/expansion.py`.
- `plan_identity`, `plan_bundle_complete`, `reuse_existing_plan`,
  `staged_plan_bundle`, `publish_plan_bundle`, `write_plan_documents`,
  `PlanConflictError`, `TARGET_PLAN_SCHEMA_VERSION`, `REQUIRED_PLAN_FILES`.
  `filing_catalog/publication.py`.
- `discover_catalogs`, `discover_plans`, `discover_policies`,
  `current_catalog_id`, `resolve_catalog_reference`, `resolve_catalog_manifest`,
  `policy_search_dirs`, `auto_policy`, `status`, `CURRENT_ALIAS`.
  `filing_catalog/discovery.py`.
- `FilingCatalogPaths`, `resolve_filing_catalog_paths`, `safe_identifier`,
  `form_partition_name`, `form_partition_dir`, `target_part_name`,
  `PIPELINE_DIR`, `SNAPSHOT_FILE_NAME`, `TARGETS_DIR_NAME`,
  `SELECTION_REPORT_NAME`, `LOCATOR_GROUPS_NAME`, `RESERVE_TARGETS_NAME`,
  `EXPANSION_METADATA_NAME`, `POLICIES_DIR_NAME`.
  `filing_catalog/paths.py`.
- `main` — the `python run.py documents` entry point.
  `document_storage/cli.py`.
- `run_document_storage`, `make_fetcher`, `new_run_id`, `RunReport`,
  `OperatorError` — Phase 2.5 run orchestration.
  `document_storage/operator.py`.
- `process_chunk`, `process_chunks`, `is_chunk_complete`,
  `chunk_checkpoint_path`, `chunk_fingerprint`, `resolved_worker_count`,
  `ChunkResult`, `DelegationTarget`, `ChunkError`, `RECLAIM_INTERVAL`,
  `WORKER_SCHEMA_VERSION`. `document_storage/worker.py`.
- `ArchiveFetcher`, `FixtureArchiveFetcher`, `BrokerArchiveFetcher`,
  `LiveArchiveFetcher`, `make_archive_fetcher`, `build_broker_fetcher`,
  `extract_from_sgml_envelope`. `document_storage/fetching.py`.
- `DocumentProcessor`, `FilingProcessor`, `PassThroughProcessor`,
  `ProcessedDocument`, `count_words`, `PROCESSOR_FINGERPRINT`,
  `PASS_THROUGH_FINGERPRINT`, `PROCESSOR_SCHEMA_VERSION`.
  `document_storage/processor.py`.
- `resolve_delegated_exhibit`, `write_exhibit_snapshot`, `exhibits_for`,
  `DelegatedExhibit`, `REFETCH_ACTION`. `document_storage/delegation.py`.
- `publish_snapshot`, `validate_chunks`, `content_fingerprint`, `read_pointer`,
  `current_snapshot_dir`, `current_snapshot_artifact`, `MergeResult`,
  `SnapshotRef`, `MergeError`, `SNAPSHOT_ARTIFACT_NAME`.
  `document_storage/merger.py`.
- `vacuum_snapshots`, `effective_relations`, `quarter_keys`,
  `validate_payload_conflicts`, `index_part_for`, `QuarterResult`,
  `VacuumError`, `DEFAULT_TARGET_BYTES`. `document_storage/vacuum.py`.
- `query_sql_batches`, `ranked_union_relations`, `effective_snapshot_relations`,
  `relation_key_rows`, `relation_payload_conflicts`, `relation_group_keys`,
  `effective_quarter_batches`, `effective_quarter_index_rows`,
  `DEFAULT_BATCH_SIZE`. `document_storage/queries.py`.
- `render_review_set`, `select_bundles`, `classify_outcome`, `write_bundle`,
  `write_manifest`, `ReviewBundle`, `ReviewResult`, `ReviewError`,
  `OUTCOME_STRATA`, `EXCERPT_CHARS`, `DEFAULT_BUNDLE_LIMIT`.
  `document_storage/review.py`.

## Commands

Every command is reachable from the repository root through `run.py`, which
dispatches on the first argument to the pipeline's module via `runpy`
(`run.py:81-88`). `python run.py` with no arguments shows the three-entry menu;
`--list` prints the ids; `-h`/`--help` prints the docstring and the list; an
unrecognized id prints `Unknown pipeline: '<id>'...` and returns 1
(`run.py:90-93`).

All three pipelines are run directly as modules as well — each `cli.py` and
Phase 1's `operator.py` have an `if __name__ == "__main__": sys.exit(main())`
guard, which the `clean-exit` scanner permits for CLI entrypoints.

### `python run.py metadata <command>` (Phase 1)

`main(argv)` builds the parser, dispatches through `args.func`, and catches
`FileNotFoundError`, `ValueError`, and `RuntimeError`, printing `error: <msg>` to
stderr and returning 1. Every successful command returns 0
(`metadata_sync/cli.py:277-289`).

| Subcommand | Flags | Returns |
| :--- | :--- | :--- |
| `plan` | `--input` (required), `--artifacts`, `--chunk-size` (default `DEFAULT_CHUNK_SIZE`), `--partition-count` (default `DEFAULT_PARTITION_COUNT`), `--workers` (default 0), `--limit` | 0; prints `plan <id> written: N CIKs, C chunks, P partitions`. No network. |
| `status` | the five common flags | 0; prints a JSON object with `plan_id`, `input_fingerprint`, `schema_version`, `planned_chunks`, `completed_chunks`, `outstanding_chunks`, `mergeable`. No network. |
| `run` | the five common flags, plus `--chunk` (int), `--partition` (int) | 0 normally; **1 when no chunks are selected** (`cli.py:155-157`). |
| `merge` | the five common flags, plus `--snapshot-id` (default `""`) | 0; prints the snapshot manifest JSON. |
| `augment` | the five common flags, plus `--base-snapshot-id` and `--new-snapshot-id` (both required) | 0; prints a JSON object with `base_snapshot_id`, `new_snapshot_id`, `base_row_count`, `delta_row_count`, `total_row_count`, `refetched_ciks`. |

`--workers 0` means machine-derived, not zero workers: `resolve_workers(0)` falls
through to `derive_resources().workers` (`worker.py:43-49`).

### `python run.py filing-catalog <command>` (Phase 2)

`main(argv)` reads `sys.argv[1:]` itself when `argv` is `None` and returns
`int(parsed.func(parsed))`. There is no top-level `try`/`except`: each command
function catches its own errors, prints `error: <msg>` to stderr, and returns 1
(`filing_catalog/cli.py:58-135, 227-231`).

| Subcommand | Flags | Returns |
| :--- | :--- | :--- |
| `materialize` | `--source`, `--source-manifest`, `--artifacts`, `--batch-size` | 0, or 1 on `CatalogError`. |
| `plan` | `--catalog` (required), `--scope` (`deterministic` default, or `policy`), `--policy`, `--auto-policy`, `--artifacts`, `--forms` (nargs `*`), `--amendment` (`both` default; choices `both`/`original`/`amendments`), `--suffixes` (nargs `*`), `--limit` | 0, or 1 on `PlanConflictError`, `ValueError`, or `OSError`. |
| `expand` | `--parent-plan` (required), `--target-units` (required, int), `--artifacts` | 0, or 1 on `PlanConflictError`, `ParentPlanError`, `ValueError`, or `OSError`. |
| `status` | `--artifacts` | 0. |

There is deliberately **no `run` subcommand**: nothing in Phase 2 performs
network work, so Phase 1's resumable-chunk lifecycle has no analogue here
(`filing_catalog/cli.py:8-9`).

Progress is written to **stderr** and the JSON result to **stdout**
(`cli.py:42-51`), so `... | jq` works.

`--scope policy` requires exactly one of `--policy PATH` or `--auto-policy`;
both together raises, and neither raises rather than silently assuming a quota
profile (`cli.py:99-114`).

### `python run.py documents <command>` (Phase 2.5)

`main(argv)` resolves paths once via `resolve_paths()`, dispatches through
`_COMMANDS`, and catches `FileNotFoundError`, `ValueError`, and `RuntimeError`
to print `error: <msg>` and return 1 (`document_storage/cli.py:211-228`).

| Subcommand | Flags | Returns |
| :--- | :--- | :--- |
| `run` | `--plan` (required), `--fixture` (required), `--run-id`, `--workers`, `--limit`, `--json` | 0 when `report.ok`, else **1** (`cli.py:150`). Returns 1 with `plan contains no chunks` on stderr if the plan yields none. |
| `status` | `--json` | 0 when a snapshot is published, else **1** (`cli.py:176`). |
| `review` | `--limit`, `--run-id`, `--json` | 0 when no bundle failed to write, else **1** (`cli.py:208`). Returns 1 if nothing is published. |

`run` is **fixture-mode by construction**: `mode="fixture"` is hardcoded at
`cli.py:133`, and `--fixture` is a required argument. Live acquisition goes
through the broker, which owns pacing, so this CLI never constructs an HTTP
client (`document_storage/cli.py:9-11`).

## Resumability and publication

### Phase 1 — the full plan / worker / merge lifecycle

1. **`plan`.** `read_cik_manifest` normalizes the CSV and takes
   `file_sha256(path)` as `input_fingerprint` (`manifest.py:95`);
   `build_plan` slices the CIK list into `chunk_size` chunks and assigns each
   chunk to a partition by `chunk_index % partition_count` (`planner.py:44-91`).
   `derive_plan_id` hashes `fingerprint:chunk_size:partition_count` and takes
   the first 16 hex characters (`planner.py:36-41`), so replanning is idempotent
   and re-chunking changes the id. The plan records `plan_format_version`,
   `schema_version`, `input_fingerprint`, chunk boundaries, and `row_count`, and
   is written atomically to `metadata/plans/<plan_id>/plan.json`.
2. **`run`.** For each target chunk, `run_chunk` first calls `inspect_chunk`;
   a valid checkpoint short-circuits the run and returns
   `ChunkResult(skipped_existing=True)` (`worker.py:177-191`). Otherwise CIKs
   are fetched concurrently on a `ThreadPoolExecutor` sized by
   `resolve_workers` (`worker.py:130`) — a thread pool, not a process pool,
   because the work is network-bound, the HTTP client and its SQLite cache are
   thread-safe, and DuckDB is confined to the coordinator
   (`worker.py:1-10`). **Every requested CIK produces exactly one row,
   including failures**, so completion is determinable from the data
   (`worker.py:8-9`). A non-terminal status is rewritten to `failed`
   (`worker.py:95-97`). The chunk is written to
   `transient/metadata/<plan_id>/chunk_NNNN.parquet`.
3. **`status`.** `discover_completed_chunks` revalidates every planned chunk
   against schema, CIK coverage, and fingerprint, and reports `mergeable:
    not outstanding`. No network.
4. **`merge`.** `validate_chunks` rejects the merge on plan coverage gaps,
   foreign chunk files, missing checkpoints, schema drift, row-count mismatch,
   CIK coverage drift, a foreign input fingerprint, or a non-terminal status
   (`merger.py:88-160`). `merge_chunks` then opens one DuckDB connection and
   refuses null CIKs and duplicate CIKs, records duplicate accessions as a
   *warning* rather than a failure, and calls
   `concat_to_parquet(..., order_by=("cik",))` — the out-of-core
   `ORDER BY cik` COPY. The merged row count must equal `plan["row_count"]` and
   the published schema must match, or the merge is rejected.
   `publish_snapshot` writes `metadata.manifest.json` and then advances
   `current/pointer.json`, both atomically.
5. **`augment`.** A separate entry point on the same machinery: plan only the
   CIKs absent from the base snapshot, run those chunks, then merge the base
   Parquet alongside the delta checkpoints. A base holding N CIKs receiving K
   new ones ends at N+K rows after exactly K fetches
   (`augmentation.py:1-7`).

On resume, nothing is refetched. `run` re-derives the plan id from the manifest
fingerprint and the effective chunking settings — there is no `--plan-id`
override, because the plan id is derived rather than chosen — `load_plan`
rejects a plan whose recorded `plan_id` does not match its own inputs or whose
`schema_version`/`plan_format_version` differs from the running build, and each
chunk is re-validated before it is skipped.

The checkpoint contract in one line: **a chunk checkpoint is complete only when
it exists, its Parquet footer schema equals `SUBMISSION_METADATA_SCHEMA`, it
holds exactly the planned CIKs, and it carries the expected input fingerprint;
anything else is treated as absent** (`checkpoints.py:1-6`).

### Phase 2 — no workers, but the same staging discipline

Phase 2 has no chunk workers. It has the publication half of the contract.
`materialize` stages under `transient/filing_catalog/<catalog_id>/` and
publishes with a single `os.replace` (`catalog_job.py:283-285`); the immutability
refusal applies to both the durable and the explicit-`output_root` path
(`catalog_job.py:202-210`). Plan bundles are staged as a *sibling* of the
destination so the final `os.replace` stays on one filesystem, and the staging
directory is removed on any failure (`publication.py:147-169`).

Plan identity is content-addressed: `plan_identity` hashes the canonicalized
request, so the same catalog and the same filters always resolve to the same
published bundle and an exact rerun reuses it rather than forking
(`publication.py:41-48, 90-96`). A directory that exists but is incomplete or
describes a different request raises `PlanConflictError` rather than being
rewritten in place.

### Phase 2.5 — per-run snapshots, then consolidation across runs

1. **Per run.** `process_chunks` skips any chunk whose checkpoint validates
   *and* whose processor fingerprint matches the processor being asked to run
   (`worker.py:109-130`); a skipped chunk's `ChunkResult` is reconstructed from
   the checkpoint so the caller sees one uniform list. Completed chunks are
   processed in a `ProcessPoolExecutor` with
   `max_tasks_per_child=RECLAIM_INTERVAL` so each child is recycled before its
   glibc arenas grow unbounded (`worker.py:457-459`). There is no separate
   "committed" ledger: **the Parquet file is the record** (`worker.py:5-7`).
2. **Delegation.** The operator runs the exhibit second pass *between* the chunks
   and the merge, because its output is itself a chunk
   (`operator.py:12-16`). It is driven by the workers' own
   `DelegationTarget` reports, so a primary is fetched and normalized exactly
   once per run, and the resolved exhibits are written to
   `chunk-delegated.parquet` with the same schema as any other chunk
   (`delegation.py:240-273`).
3. **Publication.** `publish_snapshot` validates the chunk set, assembles the
   chunks into one sorted `documents.parquet` via DuckDB out-of-core
   `COPY (... ORDER BY source_cik, accession)`, projects the artifact into an
   index part and a payload part so every published snapshot is immediately
   consolidatable, writes the manifest, and `os.replace`s staging into place.
   Only then does it publish the pointer (`merger.py:279-353`).
4. **Consolidation.** `vacuum_snapshots` resolves source manifests, validates
   part paths, builds ranked union relations, refuses conflicting normalized
   text *before writing anything*, derives the deterministic physical id, refuses
   an id that already exists, materializes each fiscal quarter in its own thread
   with a per-quarter connection, writes the manifest, and advances `current`
   (`vacuum.py:383-552`).
5. **Purge.** `purge_sources` refuses while any retained snapshot still
   references a source part; `purge_dependency_closure` instead consolidates the
   whole closure so the purge becomes safe (`vacuum.py:420-438`).

Snapshot identity is derived from the **chunks' own digests**, not from the
merged Parquet file, because a Parquet file is not byte-stable across writes
(`merger.py:188-206`).

## Tests

The test tree mirrors the source tree, one test file per source module, every
directory a package. 6,785 lines across 25 files.

- `tests/pipelines/metadata_sync/test_manifest.py` (71 loc, 6 tests)
- `tests/pipelines/metadata_sync/test_planner.py` (121 loc, 11)
- `tests/pipelines/metadata_sync/test_checkpoints.py` (110 loc, 7)
- `tests/pipelines/metadata_sync/test_worker.py` (188 loc, 10)
- `tests/pipelines/metadata_sync/test_merger.py` (315 loc, 14)
- `tests/pipelines/metadata_sync/test_augmentation.py` (303 loc, 12)
- `tests/pipelines/metadata_sync/test_end_to_end.py` (150 loc, 3) — the
  plan → run → merge replay.
- `tests/pipelines/metadata_sync/conftest.py` (24 loc) — shared setup.
- `tests/pipelines/filing_catalog/test_catalog_job.py` (297 loc, 24)
- `tests/pipelines/filing_catalog/test_planner.py` (307 loc, 22)
- `tests/pipelines/filing_catalog/test_policy_planner.py` (303 loc, 17)
- `tests/pipelines/filing_catalog/test_expansion.py` (315 loc, 20)
- `tests/pipelines/filing_catalog/test_publication.py` (218 loc, 20)
- `tests/pipelines/filing_catalog/test_discovery.py` (177 loc, 14)
- `tests/pipelines/filing_catalog/test_cli.py` (270 loc, 25)
- `tests/pipelines/filing_catalog/test_catalog_fixtures.py` (235 loc, 20)
- `tests/pipelines/filing_catalog/test_phase25_contract.py` (236 loc, 7) — the
  Phase 2 → 2.5 hand-off contract.
- `tests/pipelines/filing_catalog/conftest.py` (57 loc).
- `tests/pipelines/document_storage/test_fetching.py` (427 loc, 36)
- `tests/pipelines/document_storage/test_worker.py` (550 loc, 31)
- `tests/pipelines/document_storage/test_delegation.py` (307 loc, 16)
- `tests/pipelines/document_storage/test_merger.py` (292 loc, 15)
- `tests/pipelines/document_storage/test_vacuum.py` (730 loc, 37)
- `tests/pipelines/document_storage/test_review.py` (314 loc, 18)
- `tests/pipelines/document_storage/test_operator_and_cli.py` (466 loc, 27)
- `tests/test_network_isolation.py` — the cross-layer zero-network proof. It
  walks the import graph by AST over
  `pipelines.filing_catalog`, `engine.selection`, `domain.taxonomy`, and
  `domain.filing_catalog` and asserts none reaches `edgar_sec.infra.sec_http`. It
  lives at the test-tree root rather than mirrored because the invariant spans
  four packages, and its last test deliberately walks
  `pipelines.metadata_sync` to prove the walk is sensitive enough to find a
  dependency that does exist.

`smoke_test.py` is not collected by pytest: it is the credential-gated live path
and the default gate stays offline and deterministic
(`metadata_sync/smoke_test.py:12-14`).

Coverage is not complete against AGENTS.md §6.3's one-file-per-source-module
rule: `metadata_sync/{cli,operator,paths,sec_client,source_registry}.py`,
`filing_catalog/{paths,operator}.py`, and
`document_storage/{processor,queries}.py` have no mirrored test module. See
"Deliberate gaps".

## Deliberate gaps

- **No pipeline-level settings registry, and none is planned.** AGENTS.md §3.1
  requires phases to register their own spec dictionaries, but the three
  pipelines in this layer all read the central registry in
  `foundation/runtime/settings/` instead. That is the stronger reading of the
  rule, not a violation of it: `catalog.source_batch_size` and
  `catalog.row_group_size` are declared once in
  `foundation/runtime/settings/catalog.py` and consumed by
  `filing_catalog/catalog_job.py:166-178` through `resolve_settings()`. No
  module in this layer constructs a `SettingSpec`, reads `os.environ` (blocked
  by `environment-access`), or carries a `specs.py`.
- **No `sql-boundary` scanner, and no `defs/sql/` AST layer.** v1 policed raw SQL
  against an AST/compiler layer under `.v1/defs/sql/`. v2 removed the AST in
  favour of direct SQL, so the scanner was retired rather than ported
  (`roadmap/refactor_v2/phase_2_5.md:249-255`). The invariant actually worth
  holding is a convention, and it is stated: all consolidation SQL lives in
  `document_storage/queries.py` and executes only on connections from
  `infra/storage/duckdb.py`. The AGENTS.md scanner list registers eleven
  scanners and `sql-boundary` is not among them. Do not read its absence as an
  oversight or as permission to scatter SQL into a Phase 2.5 module.
- **Phase 1 is a metadata pipeline, not a filing pipeline.** It ingests
  `data.sec.gov` submissions JSON and unnests nothing. The document locator
  vocabulary Phase 2.5 needs is produced by Phase 2, not Phase 1.
- **No intra-package import cycle detection.** The `layer-boundary` scanner
  compares layer ranks only. Two modules inside `pipelines` importing each other
  in a cycle pass the gate. The one same-layer cross-package edge that exists —
  `filing_catalog/catalog_job.py` importing `metadata_sync/paths.py` — is
  acyclic by inspection, not by enforcement.
- **A published run snapshot is not a consolidated snapshot.** `current` can name
  either. `current_snapshot_artifact` returns `None` for a consolidated
  snapshot, which is why readers must not read "no artifact" as "nothing
  published" and use `current_snapshot_dir` to tell them apart
  (`document_storage/merger.py:376-388`). This asymmetry is deliberate and is
  the sharpest edge in this layer.
- **No incremental or partial `merge` for Phase 2.5.** `publish_snapshot`
  requires at least one usable chunk, drops invalid chunks with a warning, and
  refuses to overwrite an existing snapshot id. Correcting a bad run means
  publishing a new one, which is what makes a published identity safe to record
  in provenance elsewhere (`merger.py:1-15`).
- **`filing_catalog` has no operator action for `expand`.** The wizard offers
  status, materialize, and deterministic plan (`operator.py:68-74`), so
  policy-scoped planning and expansion are CLI-only.
- **Real-filing parity is unverified.** Phase 2.5's committed goldens are
  synthetic: `tests/fixtures/document_storage/annual_10k_html.json` and
  `annual_10k_normalization.json`. M6.3, M6.4, and M6.5 are deferred
  (`roadmap/refactor_v2/phase_2_5.md:263-265`), so no test compares this
  pipeline's output against a real SEC filing. See
  `document_storage/README.md`.
- **No scheduling, no cross-pipeline coordination, and no provenance graph.**
  Each pipeline consumes the previous one's published artifact and nothing more.
  The lineage that exists is local: `parent_plan_id` in a child `plan.json`,
  `source_snapshot_ids` in a document manifest, `input_fingerprint` in a Phase 1
  plan. There is no run registry tying the three together.
