# `edgar_sec/pipelines` — Layer 4: orchestration, command surfaces, and publication

This layer owns the parts of the system that *sequence* work: the CLI and
interactive operator, the deterministic plan, the resumable worker, and the
coordinator that decides when a dataset may be published. It is not a place for
normalization, transport, or storage primitives — every one of those is decided
in a lower layer and consumed here.

## Purpose

Six packages: five data pipelines and the cohort-management command surface. Each
owns its own package README; the details below are the layer-level contracts only.

- [`metadata_sync/`](metadata_sync/README.md) — Phase 1. Turns a
  shared CIK cohort into a manifest-described Parquet dataset snapshot. Plans
  carry a verified roster copy for distributed workers and record only the chunk
  layout, so moving a plan bundle to another machine keeps its completed chunks.
  It also consumes official shared source cohorts, projects curated inputs
  against them, and supports copy-based multi-machine distribution.
- [`filing_catalog/`](filing_catalog/README.md) — Phase 2. Zero network.
  Materializes a catalog snapshot from a Phase 1 snapshot and publishes
  immutable, content-addressed target plans for the next phase to consume.
- [`document_inventory/`](document_inventory/README.md) — Phase S1–S5 in progress.
  Projects selected cohorts, captures and replays index pages, builds parser-review
  artifacts, and contains a streamed pre-fetch projection, path-backed S4, and bounded
  S5 anti-join primitives.
- [`document_planning/`](document_planning/README.md) — offline S6 target planning
  from a digest-pinned filing-catalog plan and an optional immutable inventory
  snapshot. It publishes no acquisition work.
- [`document_storage/`](document_storage/README.md) — Phase 2.5. Fetches primary
  filings, unrolls SGML, normalizes, resolves delegated exhibits, and
  consolidates per-run snapshots into one canonical snapshot across runs.
- [`cohort/`](cohort/README.md) — Phase 0 cohort registry; manages shared cohort
  records and workspace expressions before metadata collection begins.

Layer 4 is the only layer permitted to orchestrate. Orchestration means ordering,
chunking, checkpointing, validating, and publishing — deciding *what happens
next*. Lower layers expose capabilities; a layer-4 module sequences them into a
run.

Layer 4 is not the top of the graph. `apps/` (Layer 5) sits above it and may read
everything here; the clause the scanner enforces is the reverse one — **nothing in
this package may import `apps/`**, so a batch pipeline can never take a dependency
on an operator-facing application. A non-batch consumer belongs in `apps/`, not
here.

The unifying rule of publication is that **nothing is published by a worker.**
Workers emit immutable, schema-versioned fragments into a transient tree; a
coordinator validates identity, provenance, schema, and duplicates, and only then
writes into the published tree and advances the `current` pointer. Two of the
three pipelines have workers at all.

## Layer position

`pipelines` is rank 4. It may import from `engine`, `infra`, `domain`, and
`foundation` — downward only, as AGENTS.md §1 specifies. That is not a
convention: the `layer-boundary` scanner parses each module's AST on every
`check.py` run and fails any import whose callee layer ranks above the caller's,
so no upward import out of this layer is expressible. The layer graph itself is
documented once, in AGENTS.md §1; each pipeline's own `__init__.py` states which
lower layers it depends on.

## Layout

| Module | Responsibility |
| :--- | :--- |
| `__init__.py` | Docstring only. No re-exports, per AGENTS.md §1.2. |
| `cohort/__init__.py` | Docstring only. |
| `cohort/options.py` | Cohort command grammar and argument validation. |
| `cohort/menu.py` | Grouped interactive cohort console. |
| `cohort/cli.py` | Source refresh, cohort diff/publication, catalog, import, query, sampling, and workspace dispatch. |
| `cohort/family_index.py` | Build and publish immutable family assignments from the active SEC universe. |
| `metadata_sync/__init__.py` | Docstring only. |
| `metadata_sync/cli.py` | Plan, run, augment, merge, and distribution command parsing and dispatch. |
| `metadata_sync/operator.py` | Interactive wizard; a presentation layer over the same `cmd_*` functions. |
| `metadata_sync/augment_flow.py` | Interactive cohort selection and base-snapshot choice for augmentation. |
| `metadata_sync/progress.py` | Renders this pipeline's progress events for a person; presentation only. |
| `metadata_sync/discovery.py` | What is already on disk, for the wizard to choose from. Manifest reads only. |
| `metadata_sync/worker_commands.py` | Renders the distributed lifecycle as copy-pasteable shell commands. |
| `metadata_sync/roster.py` | Metadata roster identity and IO, plus verified adaptation from Layer 2 cohort records. |
| `metadata_sync/planner.py` | `Plan`: chunk layout as roster ordinal ranges, plan identity, bundle write, and validated load. |
| `metadata_sync/assignment.py` | Static chunk-to-worker assignment and the worker receipt that crosses the machine boundary. |
| `metadata_sync/distribution.py` | Copy-based multi-machine distribution: export, select, and the import trust boundary. |
| `metadata_sync/options.py` | Typed cohort-only plan and augmentation selection; bundle path resolution. |
| `metadata_sync/worker.py` | Resumable chunk execution over a thread pool; the never-refetch guarantee. |
| `metadata_sync/checkpoints.py` | What counts as a *complete* chunk on disk. |
| `metadata_sync/snapshot.py` | Resolve a published snapshot to a verified, ordered Parquet part list. |
| `metadata_sync/merger.py` | Coordinator validation, multipart publication, progress events, CIK index, snapshot manifest, pointer. |
| `metadata_sync/augmentation.py` | Delta planning and merge onto a published snapshot without refetching the base. |
| `metadata_sync/sec_client.py` | One CIK to its submissions document plus every historical file it lists. |
| `metadata_sync/paths.py` | `MetadataPaths` / `RunPaths`; plan, snapshot, and transient locations. |
| `metadata_sync/smoke_test.py` | Credential-gated live check that never publishes. |
| `filing_catalog/__init__.py` | Docstring only. |
| `filing_catalog/cli.py` | Command dispatch, policy resolution, and the stdout/stderr split. |
| `filing_catalog/operator.py` | Interactive wizard over the same `cmd_*` functions, with discovery-driven catalog and parent-plan selection. |
| `filing_catalog/catalog_job.py` | `materialize()`: one Phase 1 snapshot in, one immutable catalog out, behind three guards. |
| `filing_catalog/planner.py` | Deterministic and policy plans; policy planning consumes a validated pre-published family index. |
| `filing_catalog/family_index.py` | Fail-closed active family-index validation for policy planning. |
| `filing_catalog/expansion.py` | Parent validation, child derivation, and the retention invariant. |
| `filing_catalog/publication.py` | Content-addressed plan ids, staged bundles, selection fingerprints, target-part digests, and reuse-or-conflict policy. |
| `filing_catalog/discovery.py` | Manifest-only catalog/plan/policy enumeration and `current` resolution. |
| `filing_catalog/paths.py` | `FilingCatalogPaths` and the artifact-name constants. |
| `document_planning/__init__.py` | Docstring only. |
| `document_planning/paths.py` | Profile, plan, and source-contract path resolution. |
| `document_planning/schemas.py` | Target relation and version contracts. |
| `document_planning/profiles.py` | Profile discovery, strict validation, and normalized requests. |
| `document_planning/catalog_scope.py` | Digest-verified filing-catalog scope stream. |
| `document_planning/inventory_evidence.py` | Pinned DAG lineage and bounded inventory evidence stream. |
| `document_planning/matching.py` | Role matching and SEC locator validation. |
| `document_planning/planner.py` | Source pins, plan identity, coverage, and target generation. |
| `document_planning/publication.py` | Atomic plan-bundle publication and exact reuse. |
| `document_planning/discovery.py` | Manifest-only status and full plan validation. |
| `document_planning/cli.py` | `plan`, `inspect`, and `status` command dispatch. |
| `document_planning/operator.py` | Evidence-mode selection and default-no publish confirmation. |
| `document_planning/commands/` | Plan, inspect, and status handlers. |
| [`document_planning/commands/README.md`](document_planning/commands/README.md) | Command package contract and deliberate gaps. |
| `document_inventory/__init__.py` | Docstring only. |
| `document_inventory/cli.py` | Fixture capture/list and offline review commands. |
| `document_inventory/operator.py` | Discovery-driven fixture and parser-review menu. |
| `document_inventory/discovery.py` | Manifest-only catalog-plan and fixture selection. |
| `document_inventory/cohort.py` | Catalog observation readers, validation, selected cohort projection, and index URL resolution. |
| `document_inventory/fixture_store/` | Mutable fixture capture, response replay, provenance, and manifest-only discovery. |
| `document_inventory/review_artifacts/` | Offline parser-review case output and inert HTML rendering. |
| `document_inventory/snapshot/` | Snapshot schemas and metadata, path resolution, DuckDB anti-join and Parquet staging. |
| `document_inventory/schemas.py` | Direct schema and relation-contract surface for Inventory consumers. |
| `document_inventory/broker.py` | Picklable SEC broker adapter and typed fetch results. |
| `document_inventory/worker.py` | Module-level per-accession process task and worker failures. |
| `document_inventory/coordinator.py` | Bounded chunk processing, attempts, resume, retry, and `run_missing_accessions`. |
| `document_inventory/paths.py` | Central inventory artifact, runtime, and transient path layout. |
| `document_inventory/run_manifest.py` | Atomic run manifest, path-backed work-order validation, and incremental chunk iteration. |
| `document_inventory/checkpoint.py` | Transient outcome schema/status, staged attempt writers, attempt manifests, chunk pointer commit, resume validation. |
| `document_storage/__init__.py` | Docstring only. |
| `document_storage/cli.py` | Command dispatch, plan-file ingestion, and the stdout/stderr split. |
| `document_storage/operator.py` | `run_document_storage()`: process chunks, resolve delegations, publish. |
| `document_storage/fixture_operator.py` | Fixture discovery and raw-payload fill operations. |
| `document_storage/candidates.py` | The pre-2005 exhibit-candidate gate and its reported population. |
| `document_storage/candidate_recovery.py` | Bundle-first recovery for pre-2005 exhibit-candidate targets. |
| `document_storage/resolution.py` | Pure filing-resolution contract: map a catalog-requested exhibit to its form-matched primary. |
| `document_storage/catalog_plan.py` | Validation and replayable streaming reads of a published `filing_catalog` plan bundle. |
| `document_storage/run_manifest.py` | Transient catalog-run identity and atomic manifest validation (`runs/<run_id>/manifest.json`). |
| `document_storage/catalog_execution.py` | Chunk-replay streaming, manifest-gated resume, and chunk status tracking for catalog plans. |
| `document_storage/work_order.py` | `ChunkInput` and the `WorkOrder` seam between an input plan and chunk execution. |
| `document_storage/fetching.py` | `ArchiveFetcher` protocol and the fixture / broker / live backends. |
| `document_storage/processor.py` | `FilingProcessor`, `PassThroughProcessor`, and the processor fingerprint. |
| `document_storage/processing.py` | Row assembly and ordinary fetch/process/delegate execution for one locator. |
| `document_storage/checkpoint.py` | Chunk-checkpoint schema and IO, fingerprint-based reuse validation, and delegation sidecars. |
| `document_storage/execution.py` | Chunk execution unit, process pool sizing, child recycling, and resume skipping. |
| `document_storage/summary.py` | Plan-derived candidate counts for a chunk, independent of any fetch. |
| `document_storage/occurrences.py` | Locator↔occurrence key mapping, expansion, and synthetic provenance rows. |
| `document_storage/parts.py` | Byte-budgeted part planning, index/payload column contracts, part-path boundary checks. |
| `document_storage/delegation.py` | The exhibit second pass for stub primaries. |
| `document_storage/merger.py` | Per-run snapshot publication: assemble, split into parts, write manifest, move pointer, idempotent reuse. |
| `document_storage/vacuum.py` | `vacuum_snapshots()`: cross-run consolidation into one canonical snapshot. Unwired — no CLI route, no production caller. |
| `document_storage/queries.py` | The direct SQL for consolidation and assembly. |
| `document_storage/paths.py` | `DocumentStoragePaths` and the published-vs-transient split. |
| `document_storage/review.py` | `compare_review_runs()`: base-vs-new review-run comparison. |
| `document_storage/review_artifacts.py` | Fixture-backed review artifact generation: selection, per-case files, manifest. |

## Contracts

**Guarantees this layer makes to its callers**

- `plan` is deterministic and performs **no network and no model calls.** Plan
  identity is derived from the plan-defining inputs rather than from a timestamp,
  so replanning an unchanged input is idempotent while changing the chunking
  produces a distinct plan. Phase 1's plan identity is the CIK *roster* plus the
  chunk layout — never an assignment, a worker count, or a timestamp — so moving a
  cohort to another machine keeps its plan directory and its completed chunks.
- A worker never writes the canonical dataset. Every worker writes an immutable,
  schema-versioned fragment under a transient root; only a coordinator publishes.
  A chunk arriving from another machine under a copied bundle is held to the same
  completeness check as a local one.
- A partial file is never treated as complete. A chunk counts only once it exists,
  carries the canonical schema, holds exactly the rows its plan's roster range
  covers, and matches the expected input fingerprint; where text conventions are a
  pipeline's own concern, a matching processor fingerprint is required too.
- Every DuckDB connection is bounded. All three pipelines call
  `infra.storage.duckdb.connect()` and never a raw `duckdb.connect()`; `connect()`
  derives `threads`, `memory_limit`, `temp_directory`, and
  `preserve_insertion_order=false` from `derive_resources()`. Hardcoding them is
  blocked by the `resource-allocation` scanner.
- Workers are sized from cgroup-aware memory, never from raw CPU count. Every
  worker count is an explicit `int | None` argument whose unset value means "derive
  it from this machine" rather than zero. `filing_catalog` has no worker: it
  batches each pass one source part at a time over a single reused connection.
- Heap is reclaimed at bounded intervals, and each pooled child is recycled after a
  bounded number of tasks, so glibc arenas cannot grow unbounded. AGENTS.md §2.2
  owns the rule; the owning worker module owns the interval.
- The `current` pointer is written only after the artifact it names exists, and
  only for the durable tree — an explicit artifacts root writes atomically but
  leaves the pointer alone, so a scratch directory can be planned from without
  disturbing published state.
- A published artifact is immutable. Each pipeline refuses to overwrite a published
  snapshot directory, rewrite a diverging plan bundle, or republish an existing
  snapshot id. Correcting a bad run means publishing a new one, which is what
  makes a published identity safe to record in provenance elsewhere.
- **Run configuration is per invocation.** Effective values follow the environment
  and the settings registry, resolved once at the options boundary. Because the plan
  id follows the effective chunk size, planning with one `--chunk-size` and running
  with another resolves a *different* plan, and the command says so rather than
  reusing another plan's checkpoints.

**Obligations callers place on this layer**

- Run every command from the repository root. `resolve_paths()` treats the working
  directory as the project root and hard-errors if it is inside the `edgar_sec`
  package, but running from any other subdirectory silently derives a second
  `.artifacts/` tree.
- Do not treat a chunk checkpoint as a dataset. Nothing in this layer exposes a
  transient path as a published one; `status` commands report published state
  only.
- Do not have a worker construct a published path. The coordinator is the only
  writer of published artifacts, and `artifact-paths` blocks `.artifacts` literals
  outside the path resolvers in `foundation/runtime/paths.py` and the per-pipeline
  `paths.py` modules.
- Do not add a fourth pipeline without updating `run.py`'s `ENTRIES` tuple, the
  `layer-boundary` layer map in AGENTS.md §1, and the repository README's layout
  section. `run.py` is the single dispatcher and it holds the list explicitly.

## Public surface

This layer publishes no re-exports: every `__init__.py` is a docstring, and
consumers import from the leaf module (AGENTS.md §1.2). The layer-level surface is
the launcher plus the shared operator policy; each pipeline's own surface is that
package README's business.

- `LauncherEntry`, `ENTRIES`, `main` — the root dispatcher registry. It holds this
  package's three pipeline ids plus the Layer 5 `viewer` app, which is why the
  entry class is not named `PipelineEntry`. `run.py` (repository root, not in this
  package).
- `operator_entrypoint`, `MenuAction`, `menu_action`, `assign_menu_keys`, `build_menu`, `prompt_text` — the shared operator policy:
  a menu with no arguments, the CLI otherwise.
  `foundation/runtime/interactive.py`.

## Command surface

Every command is reachable from the repository root through `run.py`, which
dispatches on the first argument to the entry's module via `runpy`. `python run.py`
with no arguments shows the menu; `--list` prints the ids; `-h`/`--help` prints the
docstring and the list; an unrecognized id prints an `Unknown pipeline` line naming
the id and returns 1.

| Entry id | Entrypoint module | Package |
| :--- | :--- | :--- |
| `metadata` | `metadata_sync/operator.py` | [Phase 1](metadata_sync/README.md#command-surface) |
| `filing-catalog` | `filing_catalog/operator.py` | [Phase 2](filing_catalog/README.md#command-surface) |
| `documents` | `document_storage/cli.py` | [Phase 2.5](document_storage/README.md#command-surface) |
| `viewer` | `apps/viewer/cli.py` | Layer 5, read-only |

Each linked command surface is the authoritative subcommand, flag, and exit-status
table for its package.

Each pipeline's `operator.py` carries an
`if __name__ == "__main__": sys.exit(main())` guard, as do `metadata_sync/cli.py`
and `document_storage/cli.py`, which the `clean-exit` scanner permits for CLI
entrypoints.

Two obligations hold across the layer:

- Progress traces go to **stderr** and the JSON result to **stdout**, so
  `… | jq` works.
- `--workers` unset means machine-derived, not zero.

## Resumability and publication

All three pipelines hold the AGENTS.md §4 lifecycle. The pipeline-specific
mechanics — chunk layout, checkpoint predicates, merge validation, staging and
publication, plan-bundle completeness, and consolidation — are documented in the
package READMEs. What belongs at the layer:

- **Chunk workers exist only in `metadata_sync` and `document_storage`,** and the
  two use different pool types for a stated reason: Phase 1's work is
  network-bound, so it runs on a thread pool with DuckDB confined to the
  coordinator, while Phase 2.5 normalizes a full filing document in memory, so it
  runs on a process pool.
- **Completion is recorded in the data, not in a side ledger.**
  `metadata_sync` guarantees one row per requested CIK, including failures, so
  completion is determinable from the published rows. `document_storage` publishes
  per-run snapshots and then consolidates, deriving snapshot identity from the
  chunks' own digests rather than from the merged Parquet file, which is not
  byte-stable across writes.

## Mirrored tests

The test tree mirrors the source tree, one test file per source module, every
directory a package. Mirrored pipelines tests live under `tests/pipelines/`.

Some test modules here cover cross-module contracts rather than one source module:
the Phase 1 plan → run → merge replay, scale and reassignment convergence, the
Phase 1 / Phase 2.5 settings-default contract, and the Phase 2 → Phase 2.5 plan
bundle interface. `metadata_sync/smoke_test.py` is the credential-gated live path;
its argument guards are covered offline and its live fetch is never exercised.

`tests/test_network_isolation.py` is the cross-layer zero-network proof. It walks
the import graph by AST over `pipelines.filing_catalog`, `engine.selection`,
`domain.taxonomy`, and `domain.filing_catalog` and asserts none reaches
`edgar_sec.infra.sec_http`. It lives at the test-tree root rather than mirrored
because the invariant spans four packages, and its last test deliberately walks
`pipelines.metadata_sync` to prove the walk is sensitive enough to find a
dependency that does exist.

Coverage meets AGENTS.md §6.3's one-file-per-source-module rule for
`metadata_sync` and `filing_catalog`. In `document_storage`, `operator.py` and
`cli.py` share one test module, and `processor.py` and `queries.py` have none —
their symbols are exercised from the worker, delegation, and vacuum tests, so
nothing is untested, but a regression isolated to one of them is not reported as
its own failure.

## Deliberate gaps

- **Phase 1 is a metadata pipeline, not a filing pipeline.** It ingests
  `data.sec.gov` submissions JSON and unnests nothing. The document locator
  vocabulary Phase 2.5 needs is produced by Phase 2.
- **No intra-package import cycle detection.** The `layer-boundary` scanner
  compares layer ranks only, so it cannot catch a cycle between two modules of this
  layer or between two packages in it. A same-layer cross-package edge exists
  today — `filing_catalog` reads `metadata_sync`'s path and snapshot helpers — and
  it is acyclic by inspection, not by enforcement.
- **No pipeline's menu asks for an artifacts root.** Launcher entries resolve the
  configured project root, and a non-default root is a per-command `--artifacts`
  flag. Only `filing_catalog` and `metadata_sync` expose that flag;
  `document_storage` has none and is bound to the configured root. `viewer` is the
  same at the CLI (`--artifacts`, optional) and is not interactive at all.
- **Real-filing parity is unverified for Phase 2.5** — its committed goldens are
  synthetic. See [`document_storage/README.md`](document_storage/README.md#deliberate-gaps).
- **No scheduling, no cross-pipeline coordination, and no provenance graph.**
  Each pipeline consumes the previous one's published artifact and nothing more.
  The lineage that exists is local: `parent_plan_id` in a child `plan.json`,
  `source_snapshot_ids` in a document manifest, `input_fingerprint` in a Phase 1
  plan. There is no run registry tying the three together.
