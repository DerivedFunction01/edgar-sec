# `edgar_sec/pipelines` — Layer 4: orchestration, command surfaces, and publication

This layer owns the parts of the system that *sequence* work: the CLI and
interactive operator, the deterministic plan, the resumable worker, and the
coordinator that decides when a dataset may be published. It is not a place for
normalization, transport, or storage primitives — every one of those is decided
in a lower layer and consumed here.

## Purpose

Data pipelines and the cohort-management command surface each own a package README;
the details below are the layer-level contracts only.

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
- [`document_acquisition/`](document_acquisition/README.md) — initial S9 path and
  handoff-contract foundation with S6 bundle projection and a registered
  CLI/operator. Network acquisition is not implemented; S10 and S11 remain gated.
  Its [`fixture_store/`](document_acquisition/fixture_store/README.md) subpackage
  owns compressed SQLite response evidence and incremental replay only.
  Its [`run_state/`](document_acquisition/run_state/README.md) subpackage owns the
  mutable per-run SQLite ledger and token-owned locks.
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
- Do not add a pipeline command without updating `run.py`'s `ENTRIES` tuple, the
  `layer-boundary` layer map in AGENTS.md §1, and the repository README's layout
  section. `run.py` is the single dispatcher and it holds the list explicitly.

## Command surface

<!-- AUTOGEN:COMMANDS:START -->
<!-- AUTOGEN:COMMANDS:END -->

### Usage examples

Every command is reachable from the repository root through `run.py`, which
dispatches on the first argument to the entry's module via `runpy`. `python run.py`
with no arguments shows the menu; `--list` prints the ids; `-h`/`--help` prints the
docstring and the list; an unrecognized id prints an `Unknown pipeline` line naming
the id and returns 1.

Commands: `metadata`, `filing-catalog`, `documents`, `viewer`. Each entry points to its pipeline's operator module. Linked command surfaces in package READMEs are authoritative for subcommands, flags, and exit codes.

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
