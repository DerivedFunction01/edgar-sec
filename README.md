# edgar-sec (v2)

High-performance, memory-safe SEC EDGAR extraction engine and pipeline. Transforms SEC submissions and filing disclosures into clean, versioned, queryable columnar datasets (Parquet / Arrow / DuckDB).

---

## Architecture Overview

`edgar_sec` is built from Layer 0 up with strict acyclic downward-only dependencies:

```text
Layer 5: apps/         # Read-only, operator-facing consumers of published artifacts
Layer 4: pipelines/    # High-level orchestrators, CLI, and resumable execution
Layer 3: engine/       # Normalization, array unrolling, Arrow batch construction
Layer 2: infra/        # SEC HTTP transport, token-bucket rate limiter, DuckDB storage
Layer 1: domain/       # Identity types (Cik, AccessionNumber) and schema definitions
Layer 0: foundation/   # Crypto, cgroup resources, memory reclamation, settings registry, scanners
```

---

## Non-Regression Memory & Performance Guarantees

1. **Cgroup & Multi-Worker Safety**:
   - `auto_worker_count()` calculates worker processes from cgroups v2/v1 and `/proc/meminfo` `MemAvailable` (with 512 MiB budget and 90% safety limit) to prevent host OOM kills.
2. **glibc Arena Reclamation**:
   - `reclaim()` executes `gc.collect()` and `malloc_trim(0)` to prevent resident heap fragmentation in long-running batch runs.
3. **DuckDB Out-of-Core Spill Protection**:
   - All DuckDB connections run under machine-profiled memory limits, threads, and managed spill directories with `preserve_insertion_order=false`.
4. **Streaming Hashing**:
   - `sha256_text()` uses 1MB memoryview chunks to prevent memory spikes on multi-megabyte submissions.
5. **Automated Scanner Enforcement**:
   - Modular policy scanners in `check.py` guarantee that hardcoded resources, environment bypasses, or upward layer imports cannot be committed.

---

## Quick Start

> [!IMPORTANT]
> **Run every command from the repository root.** The artifacts, uploads, and
> cache roots are all derived from the current working directory, so running
> from inside `edgar_sec/` would derive a second, parallel `.artifacts/` tree
> beside the package and silently report an empty catalog. The engine now
> refuses to start in that directory.

### 1. Interactive Launcher
```bash
# Launch interactive dispatcher menu:
python run.py
```

### 2. Run the Quality Gate
```bash
# Full verification gate (format, lint, scanners, tests):
.venv/bin/python check.py

# Auto-fix formatting and safe lints (< 0.5s; does NOT run tests):
.venv/bin/python check.py --fix

# Fast static verification during development (~1s; skips tests):
.venv/bin/python check.py --fast
```

### 3. Generate Documented .env Template
```bash
# Generate documented environment configuration:
python -c "from edgar_sec.foundation.runtime.settings import render_dotenv; print(render_dotenv())" > .env
```

### 4. Metadata Sync Pipeline
```bash
# Capture an immutable external source snapshot, then project the curated input
# against it to find registrants upstream that the CSV does not cover:
python run.py metadata sources refresh
python run.py metadata sources compare --input uploads/cik-sec.csv \
    --source-manifest <artifacts-root>/metadata/sources/company_tickers/<id>/manifest.json

# Plan a cohort (deterministic, no network). --input takes a curated CSV;
# --roster takes a published effective CIK roster id from `sources compare`.
python run.py metadata plan --input uploads/cik-sec.csv
python run.py metadata plan --roster <registry_id>

# Inspect progress and outstanding chunks (no network):
python run.py metadata status --input uploads/cik-sec.csv

# Execute outstanding chunks (resumable; completed chunks are never refetched):
python run.py metadata run --input uploads/cik-sec.csv

# Validate every chunk and publish a sorted snapshot:
python run.py metadata merge --input uploads/cik-sec.csv

# Add newly requested CIKs to an existing snapshot without refetching the base:
python run.py metadata augment --input uploads/cik-sec-new.csv \
    --base-snapshot-id <id> --new-snapshot-id <id>
```

Run one cohort across several machines by copying the plan bundle out. The
bundle is byte-identical for every worker; only the assignment differs.
```bash
# Coordinator: one bundle per worker, each with a disjoint chunk list.
python run.py metadata export --plan-id <plan_id> --worker-count 4 \
    --destination /tmp/metadata-out

# On each machine, after copying the bundle across:
python run.py metadata worker --bundle /tmp/metadata-out/worker-00

# Back on the coordinator: verify and adopt the returned chunks.
python run.py metadata import --plan-id <plan_id> \
    --source /tmp/metadata-out/worker-00
```

`--plan-id`, `--bundle`, and `--input`/`--roster` are interchangeable ways to
name a plan; a copied bundle names its own plan in its manifest. Effective
chunking comes from `--chunk-size`, else `RUNTIME_CHUNK_SIZE`, else the code
default. Keep it stable across `plan`, `run`, and `merge`: the plan id is derived
from the roster identity and the effective chunk size, so changing the chunking
resolves a different plan and the command fails loudly rather than reusing
mismatched checkpoints. There is no persisted project configuration and no
`--configure`. Assigning work is a separate artifact, so changing the worker
count never moves the plan or discards completed chunks. Note that each worker
process builds its own rate limiter, so divide the budget with
`SEC_RATE_LIMIT_RPS` when distributing across machines.

### 5. Filing Catalog Pipeline (Zero Network)

Phase 2 turns a finalized Phase 1 snapshot dataset into immutable,
content-addressed **target plans** for a future acquisition phase to consume.
It never performs network I/O, and `tests/test_network_isolation.py` proves
that by walking the import graph rather than by grep.

`materialize` writes **one target shard per Phase 1 source part**. A Phase 1
registrant row carries its whole filing history as a nested array, so unnesting
the entire cohort at once exhausts the memory limit; staging part by part bounds
peak memory by the densest single part. The shards are each ordered by the
projection key but are **not** globally sorted — they follow Phase 1 source-part
order, and `snapshot.manifest.json` records `sort_order: "source_part_order"` so a
consumer cannot mistake one shard's ordering for a dataset-wide guarantee. There
is no `--batch-size` flag; the Phase 1 part is the unit of work.

```bash
# Materialize a catalog snapshot from a Phase 1 snapshot:
python run.py filing-catalog materialize \
    --source-manifest <phase1>/metadata/snapshots/<id>/metadata.manifest.json

# Deterministic plan: four filters including --dates, 8-column locator projection.
# Forms are exact: an amendment variant such as 10-K/A must be named explicitly.
python run.py filing-catalog plan --catalog current --forms 10-K
# Narrow it by report_date: one quoted union of absolute windows and recurring periods.
python run.py filing-catalog plan --catalog current \
    --dates "@Q1[1999..2001],2005Q3..2008Q1,2011-12-31..2019-11-03"

# Policy plan: fill a declared quota profile. Era-stratified, 18 columns.
python run.py filing-catalog plan --catalog current --scope policy \
    --policy artifacts/filing_catalog/policies/corpus.json
# ...or derive a baseline policy from the catalog's own forms and year range:
python run.py filing-catalog plan --catalog current --scope policy --auto-policy

# Scale a policy plan. The child retains 100% of the parent's locators.
# Plan bundles are direct children of filing_catalog/, not under plans/:
python run.py filing-catalog expand --parent-plan artifacts/filing_catalog/<plan_id> \
    --target-units 10000

# Published state, from manifests only (zero Parquet reads):
python run.py filing-catalog status
```

**Artifact layout.** Snapshots and plans are published immutable; staging lives
under `artifacts_root/transient/`.

```text
artifacts_root/filing_catalog/
├── snapshots/                          # mirrors metadata/snapshots/
│   ├── <catalog_id>/                   # immutable catalog snapshot
│   │   ├── snapshot.manifest.json
│   │   ├── company_profiles.parquet    # 23 columns, projected from Phase 1
│   │   └── filing_targets/part-NNNNN.parquet   # one shard per Phase 1 source part
│   └── current/pointer.json            # current catalog pointer
├── plans/<plan_id>/                    # immutable plan bundle
│   ├── plan.json
│   ├── selection_report.json
│   ├── seed_filers.csv                 # policy scope only
│   ├── locator_groups.parquet          # 8 cols (deterministic) or 18 (policy)
│   ├── reserve_targets.parquet         # policy scope only
│   ├── expansion_metadata.json         # child plans only
│   └── targets/form=<FORM>/data.parquet
├── policies/
└── snapshots/<feature-digest>/           # Stage B feature snapshot (policy
                                         #   scope only; identified by
                                         #   feature_snapshot.json, not by name)
```

Catalog snapshots and plan bundles are siblings under `filing_catalog/`, matching
`metadata/snapshots/` and `metadata/plans/`, and the `current` pointer lives
inside `snapshots/`. An earlier revision put both kinds directly under
`filing_catalog/` and argued they could never collide because both ids are
24-character digests — true, but it left a tree in which nothing distinguished a
snapshot from a plan by name. `targets/form=<FORM>/data.parquet` is
scope-specific: a deterministic plan
publishes the raw `TARGET_COLUMNS`, a policy plan the feature-enriched
occurrence rows it selected from. `locator_groups.parquet` is the scope-
independent work order.

**Selecting a balanced sample.** The one property that matters most: a corporate
group with 400 subsidiaries files 400 documents, so a naive sample of filings is
mostly that group. Every candidate is keyed by a six-part classification
signature — `(company_family, form, era, sic_code, entity_type, lifecycle_class)`
— and at most `max_per_company_classification` candidates may share one. Because
every subsidiary of a group resolves to one `company_family`, the cap suppresses
the group without special-casing it. A floor the corpus cannot satisfy is
reported in `plan.json` rather than silently absorbed.

### 6. Document Storage (Phase 2.5)

Phase 2.5 fills append-only raw-payload fixture stores, then replays document
plans offline from those stores. A fixture uses
`artifacts_root/fixtures/<fixture_id>/fixture.sqlite` with the single canonical
table `fixture_payloads(doc_id, raw_payload)` and a sibling
`fixture.manifest.json`. Existing locator rows are skipped, successful responses
are never overwritten, and unsuccessful locators can be retried on a later fill.
An SGML submission bundle is stored intact when fetched so replay can repeat
subdocument extraction.

```bash
# Fetch missing raw responses from a document chunk-plan JSON:
python run.py documents fill --plan corpus.json --fixture fix-corpus --workers 4

# List fixture IDs, payload counts, and manifest validity:
python run.py documents fixtures

# Replay offline; repeat --fixture to define first-store-wins precedence:
python run.py documents run --plan corpus.json --fixture fix-corpus
```

Running `python run.py documents` opens a phase-local menu for fill, replay, and
fixture listing. The CLI does not require v1 plan history or legacy processing
tables; those tables are neither migrated nor read.

### 7. Live Smoke Test (Credential-Gated, Outside the Gate)
```bash
# Bounded live SEC check. Never publishes a snapshot; requires a preview root.
python -m edgar_sec.pipelines.metadata_sync.smoke_test \
    --input tests/fixtures/cik_sec_mini.csv --sample-size 3 --artifacts preview/metadata
```

---

## Component Documentation

Every package owns a `README.md` stating its purpose, a module
layout table, the contracts it guarantees, its mirrored tests, and its
**deliberate gaps** — what it intentionally does not contain, so an absent
capability is never mistaken for an oversight. `AGENTS.md` is normative where
the two disagree.

### (package root)

- [`README.md`](edgar_sec/README.md)

### foundation

- [`foundation/README.md`](edgar_sec/foundation/README.md)
- [`foundation/regex/README.md`](edgar_sec/foundation/regex/README.md)
- [`foundation/runtime/README.md`](edgar_sec/foundation/runtime/README.md)
- [`foundation/runtime/settings/README.md`](edgar_sec/foundation/runtime/settings/README.md)
- [`foundation/scanners/README.md`](edgar_sec/foundation/scanners/README.md)
- [`foundation/text/README.md`](edgar_sec/foundation/text/README.md)

### domain

- [`domain/README.md`](edgar_sec/domain/README.md)
- [`domain/document/README.md`](edgar_sec/domain/document/README.md)
- [`domain/filing_catalog/README.md`](edgar_sec/domain/filing_catalog/README.md)
- [`domain/forms/README.md`](edgar_sec/domain/forms/README.md)
- [`domain/submissions/README.md`](edgar_sec/domain/submissions/README.md)
- [`domain/taxonomy/README.md`](edgar_sec/domain/taxonomy/README.md)

### infra

- [`infra/README.md`](edgar_sec/infra/README.md)
- [`infra/broker/README.md`](edgar_sec/infra/broker/README.md)
- [`infra/sec_http/README.md`](edgar_sec/infra/sec_http/README.md)
- [`infra/storage/README.md`](edgar_sec/infra/storage/README.md)

### engine

- [`engine/README.md`](edgar_sec/engine/README.md)
- [`engine/company_family/README.md`](edgar_sec/engine/company_family/README.md)
- [`engine/document/README.md`](edgar_sec/engine/document/README.md)
- [`engine/document/html/README.md`](edgar_sec/engine/document/html/README.md)
- [`engine/document/unpacking/README.md`](edgar_sec/engine/document/unpacking/README.md)
- [`engine/document/page_markers/README.md`](edgar_sec/engine/document/page_markers/README.md)
- [`engine/document/whitespace/README.md`](edgar_sec/engine/document/whitespace/README.md)
- [`engine/tables/README.md`](edgar_sec/engine/tables/README.md)
- [`engine/tables/ascii_html/README.md`](edgar_sec/engine/tables/ascii_html/README.md)
- [`engine/tables/false_tables/README.md`](edgar_sec/engine/tables/false_tables/README.md)
- [`engine/tables/hybrid/README.md`](edgar_sec/engine/tables/hybrid/README.md)
- [`engine/tables/protection/README.md`](edgar_sec/engine/tables/protection/README.md)
- [`engine/forms/README.md`](edgar_sec/engine/forms/README.md)
- [`engine/forms/plugins/README.md`](edgar_sec/engine/forms/plugins/README.md)
- [`engine/forms/plugins/evaluators/README.md`](edgar_sec/engine/forms/plugins/evaluators/README.md)
- [`engine/selection/README.md`](edgar_sec/engine/selection/README.md)
- [`engine/submissions/README.md`](edgar_sec/engine/submissions/README.md)

All seven Phase 2.5 sub-plan 03/04 slices have returned. `engine/tables/` has its masking,
HTML→ASCII rendering, false-table rejection, and boundary resolver; `engine/reflow/` its
features, calibrated thresholds, and rule cascades; `engine/forms/` its cover decision chain,
family SPI, and evaluators.

### pipelines

- [`apps/README.md`](edgar_sec/apps/README.md)
- [`apps/viewer/README.md`](edgar_sec/apps/viewer/README.md)
- [`foundation/sql/README.md`](edgar_sec/foundation/sql/README.md)
- [`pipelines/README.md`](edgar_sec/pipelines/README.md)
- [`pipelines/document_storage/README.md`](edgar_sec/pipelines/document_storage/README.md)
- [`pipelines/filing_catalog/README.md`](edgar_sec/pipelines/filing_catalog/README.md)
- [`pipelines/metadata_sync/README.md`](edgar_sec/pipelines/metadata_sync/README.md)

---

## Repository Layout

```text
edgar_sec/               # each package has its own README.md (see above)
├── foundation/         # Layer 0: runtime, memory, hashing, serialization,
│                       #   zstd compression, settings registry, scanners
├── domain/             # Layer 1: Cik/Accession, document, forms and cover
│                       #   vocabulary, taxonomy, submission and catalog schemas
├── infra/              # Layer 2: SEC HTTP client, broker, atomic IO, DuckDB,
│                       #   Parquet, snapshot manifests, part tree, fixture store
├── engine/             # Layer 3: SGML unpacking, selectolax tree access, the
│                       #   normalization seam and FormPlugin SPI, candidate
│                       #   selection, company families, submission building.
│                       #   Partially built — see engine/README.md
├── pipelines/          # Layer 4: metadata_sync (Phase 1), filing_catalog
│                       #   (Phase 2), document_storage (Phase 2.5)
└── apps/               # Layer 5: the dataset viewer (read-only, no publishing)

tests/                      # Test tree mirrors the edgar_sec/ package tree
├── support.py              # Shared fixture access and offline HTTP test doubles
├── fixtures/               # Committed golden fixtures (cross-layer)
├── foundation/             # hashing, serialization, zstd compression
│   ├── regex/              # builder DSL, trie compaction
│   ├── runtime/            # env, memory, paths, settings, partitions, resources
│   ├── scanners/           # one test module per policy scanner
│   └── text/               # dates, tokens, grammar, patterns, automaton
├── domain/                 # identity, document, forms, taxonomy, submissions
├── infra/
│   ├── broker/             # Unix-socket broker client/server
│   ├── sec_http/           # client, cache, rate_limit, retry, errors
│   └── storage/            # atomic, duckdb, parquet, manifests,
│                           #   document parts, fixture store
├── engine/
│   ├── document/           # unpacking (SGML, ascii-pre, representation), html
│   │                       #   (tags, tree, cleaner, breaks, normalizer), page_markers
│   │                       #   (models, candidates, sequence, units, templates, artifacts,
│   │                       #   policy, signatures), whitespace
│   ├── forms/              # normalize seam, cover, checkmarks, evaluators, plugins
│   ├── reflow/             # rule engine, features, registry, types
│   ├── tables/             # resolver, structural, false tables, ascii_html
│   ├── selection/          # features, inventory, policy, selector, source
│   ├── company_family/     # normalizer, clustering
│   └── submissions/        # unroller, builder, profile
└── pipelines/
    ├── metadata_sync/      # manifest, roster, planner, assignment,
    │                       # distribution, options, checkpoints, worker,
    │                       # merger, augmentation, source_registry,
    │                       # registry, sec_client, smoke_test, operator, cli
    ├── filing_catalog/     # discovery, expansion, planner, publication, cli
    └── document_storage/   # fixture_operator, fetching, processor, worker,
                            # delegation, merger, vacuum, queries, operator,
                            # cli, review
└── apps/
    └── viewer/             # model, loaders, tree, session, datasets,
                            # console, server, cli, ui/ (React client,
                            # dist committed)

check.py                # Unified repository quality gate runner
run.py                  # Interactive terminal workflow dispatcher
ruff.toml               # Lint configuration (suppressions live here, not in code)
AGENTS.md               # Binding engineering contract and design guidelines
roadmap/                # Multi-phase product roadmap specifications
```

### Test Layout Convention

The test tree mirrors the source package tree, so a test file sits beside the
module it covers at the same relative path. This keeps a module's tests
discoverable by path and stops the suite from degrading into a flat list as
more modules and pipelines are added. Every test directory is a package
(owns `__init__.py`), which keeps pytest module names unambiguous.

Fixture access goes through `tests.support` rather than `parents[N]` depth
arithmetic, so reorganizing the tree does not break test paths.

---

## Artifact Layout

All generated paths derive from the artifacts root; no module hardcodes them.

```text
{artifacts_root}/metadata/plans/{plan_id}/plan.json            # Small plan manifest
{artifacts_root}/metadata/plans/{plan_id}/roster/ciks.parquet    # The CIK cohort, once
{artifacts_root}/metadata/plans/{plan_id}/input/                 # Where the cohort came from
{artifacts_root}/metadata/plans/{plan_id}/assignments/*.parquet   # One chunk set per worker
{artifacts_root}/transient/metadata/{plan_id}/chunk_NNNN.parquet # Resumable checkpoints
{artifacts_root}/metadata/registries/{registry_id}/             # Source comparison outputs
{artifacts_root}/metadata/snapshots/{snapshot_id}/parts/*.parquet   # Published dataset
{artifacts_root}/metadata/snapshots/{snapshot_id}/ciks.parquet     # Published CIK index
{artifacts_root}/metadata/snapshots/current/pointer.json        # Current snapshot pointer
{artifacts_root}/metadata/sources/{name}/{snapshot_id}/         # Immutable source snapshots

{artifacts_root}/filing_catalog/<catalog_id>/               # Immutable catalog snapshot
{artifacts_root}/filing_catalog/<plan_id>/                  # Immutable plan bundle
{artifacts_root}/filing_catalog/current/pointer.json        # Current catalog pointer
{artifacts_root}/transient/filing_catalog/<catalog_id>/     # Staging; never published

{artifacts_root}/fixtures/<fixture_id>/fixture.sqlite      # Raw replay payloads
{artifacts_root}/fixtures/<fixture_id>/fixture.manifest.json
{artifacts_root}/document_storage/snapshots/<snapshot_id>/  # Published documents
{artifacts_root}/transient/document_storage/runs/<run_id>/ # Resumable run staging
```

### Merge Semantics

Two classes of finding are deliberately distinguished:

- **Failures** — duplicate or null CIKs, schema drift, plan coverage gaps, mismatched row counts, foreign chunk files, non-terminal statuses.
- **Reportable fan-out** — duplicate accessions. The same filing is legitimately listed by more than one registrant, so duplicates are surfaced as a warning and never reject a merge.

---

## Engineering Contract

Refer to [`AGENTS.md`](AGENTS.md) for full engineering rules, layer boundary constraints, and verification protocols.
