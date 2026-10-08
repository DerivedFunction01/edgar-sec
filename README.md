# edgar-sec

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
Layer 0: foundation/   # Shared primitives, runtime/fixture paths, resource budgets, settings, scanners
```

[AGENTS.md §1](AGENTS.md) is normative for the layer rules and what each layer may import; a policy scanner enforces the graph.

---

## Resource & Memory Guarantees

1. **Cgroup-aware worker sizing** — worker counts derive from cgroup or `/proc/meminfo` memory headroom, never from raw CPU count, so a large host cannot overcommit a small container.
2. **Bounded DuckDB** — every connection takes its threads, memory limit, and spill directory from that same budget.
3. **Streaming hashing** — digests stream in blocks, so hashing a multi-megabyte filing never materializes a second full-size copy.
4. **Scanner enforcement** — `check.py` refuses hardcoded resource limits, environment bypasses, and upward layer imports.

[AGENTS.md §2](AGENTS.md) states each guarantee and the scanner that enforces it.

---

## Quick Start

> [!IMPORTANT]
> **Run every command from the repository root.** The artifacts, uploads, and
> cache roots all derive from the current working directory, so running from
> inside `edgar_sec/` would derive a second, parallel `.artifacts/` tree and
> silently report an empty catalog. The engine refuses to start there.

### Interactive Launcher
```bash
# Launch interactive dispatcher menu:
python run.py
```

### Phase 0: Cohort Management
```bash
# Import and inspect a cohort:
python run.py cohort import --input uploads/cik-sec.csv --name uploaded
python run.py cohort list
python run.py cohort query uploaded --limit 10
# Refresh sources here, outside metadata_sync:
python run.py cohort sources refresh --source cik_lookup
# After publishing the source:
python run.py cohort family-index

# Compare two cohorts; optionally publish either directional delta:
python run.py cohort diff universe tickers \
    --save-left-delta sec-only --save-right-delta ticker-only

# Combine sources, preferring the official SEC names on the left:
python run.py cohort merge --expr "official + uploaded" --name combined
```

Membership is deduplicated by CIK. Duplicate input rows select the first
non-empty trimmed name; unions/intersections prefer the left operand's non-empty
name, then the right. Put the label source you trust first.

### Quality Gate
```bash
# Full verification gate (format, lint, scanners, tests):
.venv/bin/python check.py

# Auto-fix formatting and safe lints; does NOT run tests:
.venv/bin/python check.py --fix

# Fast static verification during development; skips tests:
.venv/bin/python check.py --fast
```

### Environment Template
```bash
# Generate documented environment configuration:
python -c "from edgar_sec.foundation.runtime.settings import render_dotenv; print(render_dotenv())" > .env
```

### Metadata Sync Pipeline
```bash
# Plan one published cohort (deterministic, no network). Select an id, name,
# or active alias such as universe or tickers; metadata does not refresh sources.
python run.py metadata plan --cohort uploaded
python run.py metadata plan --cohort universe

# Inspect progress and outstanding chunks (no network):
python run.py metadata status --cohort uploaded

# Execute outstanding chunks (resumable; completed chunks are never refetched):
python run.py metadata run --cohort uploaded

# Validate every chunk and publish a snapshot:
python run.py metadata merge --cohort uploaded

# Add newly requested CIKs to an existing snapshot without refetching the base:
python run.py metadata augment --cohort uploaded \
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

`--plan-id`, `--bundle`, and `--cohort` are ways to identify the plan for status,
run, and merge; a copied bundle names its own plan in its manifest. Keep the
effective chunk size stable across `plan`, `run`, and `merge` — it comes from
`--chunk-size`, else `RUNTIME_CHUNK_SIZE` — because the plan id is derived from
the roster identity and that chunk size, so changing it resolves a different plan
and the command fails loudly rather than reusing mismatched checkpoints.
Assignment is a separate artifact, so changing the worker count never moves the
plan or discards completed chunks. Each worker process builds its own rate
limiter, so divide the budget with `SEC_RATE_LIMIT_RPS` when distributing across
machines. The full command surface is in the
[metadata_sync package README](edgar_sec/pipelines/metadata_sync/README.md).

### Filing Catalog Pipeline (Zero Network)

Phase 2 turns a finalized Phase 1 snapshot dataset into immutable,
content-addressed **target plans** for a future acquisition phase to consume.
It never performs network I/O, and `tests/test_network_isolation.py` proves
that by walking the import graph rather than by grep.

```bash
# Materialize a catalog snapshot from a Phase 1 snapshot:
python run.py filing-catalog materialize \
    --source-manifest <phase1>/metadata/snapshots/<id>/metadata.manifest.json

# Deterministic plan, filtered by form and report date:
# Forms are exact: an amendment variant such as 10-K/A must be named explicitly.
python run.py filing-catalog plan --catalog current --forms 10-K
# Restrict deterministic targets to a shared cohort:
python run.py filing-catalog plan --catalog current --cohort <cohort_id>
# Narrow it by report_date: one quoted union of absolute windows and recurring periods.
python run.py filing-catalog plan --catalog current \
    --dates "@Q1[1999..2001],2005Q3..2008Q1,2011-12-31..2019-11-03"

# Policy plan: fill a declared quota profile across filing eras.
# Publish the current universe's family index before planning.
python run.py cohort family-index
python run.py filing-catalog plan --catalog current --scope policy \
    --policy artifacts/filing_catalog/policies/corpus.json
# Or seed a policy plan from a shared cohort:
python run.py filing-catalog plan --catalog current --scope policy \
    --policy artifacts/filing_catalog/policies/corpus.json --seed-cohort <cohort_id>
# ...or derive a baseline policy from the catalog's own forms and year range:
python run.py filing-catalog plan --catalog current --scope policy --auto-policy

# Scale a policy plan while retaining the parent's selected locators.
python run.py filing-catalog expand \
    --parent-plan artifacts/filing_catalog/plans/<plan_id> \
    --target-units 10000

# Inspect published state:
python run.py filing-catalog status
```

**Artifact layout.** Snapshots and plans are published immutable; staging lives
under `artifacts_root/transient/`.

Fixtures share the dataset-scoped layout and versioned manifest envelope provided
by `foundation.runtime.fixtures`; each pipeline owns its fixture details and payload
schema. The document-storage and document-inventory roots are shown below.

```text
artifacts_root/filing_catalog/
├── snapshots/                          # mirrors metadata/snapshots/
│   ├── <catalog_id>/                   # immutable catalog snapshot
│   │   ├── snapshot.manifest.json
│   │   ├── company_profiles.parquet    # projected profile data
│   │   └── filing_targets/part-NNNNN.parquet   # source-part target shards
│   ├── <feature-digest>/               # policy-scope feature snapshot, identified by
│   │                                   #   feature_snapshot.json, not by name
│   └── catalog.sqlite                  # SQLite DAG catalog database
├── plans/<plan_id>/                    # immutable plan bundle
│   ├── plan.json
│   ├── selection_report.json
│   ├── seed_filers.csv                 # policy scope only
│   ├── locator_groups.parquet          # schema depends on planning scope
│   ├── reserve_targets.parquet         # policy scope only
│   ├── expansion_metadata.json         # child plans only
│   └── targets/form=<FORM>/data.parquet
└── policies/
```

Target shards follow Phase 1 source-part order rather than being globally
sorted — `sort_order: source_part_order` in the snapshot manifest — and
`locator_groups.parquet` is the scope-independent work order. See the
[filing_catalog package README](edgar_sec/pipelines/filing_catalog/README.md)
for the plan contract and the [selection package README](edgar_sec/engine/selection/README.md)
for policy plans, which cap over-represented company families and report unmet
quota floors instead of silently absorbing them.

### Document Storage (Phase 2.5)

Document storage saves raw responses to append-only fixture stores so a plan can
be replayed offline. Existing payloads are not overwritten, and failed locators
can be retried on a later fill. It also performs candidate-gated recovery: for
pre-2005 exhibit-target candidates it acquires the submission bundle first,
resolves the requested exhibit against the form-matched primary, and dual-writes
both rows with role, parent, provenance, and outcome in the persisted `metadata`.

Execution over a catalog plan is resumable under the same run ID: an atomic
transient run manifest (`runs/<run_id>/manifest.json`) records input and plan
identity before fetching begins, replaying validated completed chunks and
durable delegation sidecars while computing only incomplete work. Same-run
publication retries validate existing snapshot artifacts and part digests
idempotently without mutation. Generic and JSON-plan runs remain fresh-only.
Fixture lineage checks the most recent fill; fixture payloads are not hashed,
so lineage does not certify complete offline payload coverage. See the
[pipeline README](edgar_sec/pipelines/document_storage/README.md) for persistence
details.

```bash
# Fetch missing raw responses from a document chunk-plan JSON:
python run.py documents fill --plan corpus.json --fixture fix-corpus

# List fixture IDs, payload counts, and manifest validity:
python run.py documents fixtures

# Replay offline; repeat --fixture to define first-store-wins precedence:
python run.py documents run --plan corpus.json --fixture fix-corpus
```

Running `python run.py documents` opens a phase-local menu over the fixture
lifecycle: fill, replay, listing, review artifacts, and review comparison. It
operates on the current plan and fixture formats; it does not migrate or read
unrelated processing tables.

### Live Smoke Test (Credential-Gated, Outside the Gate)
```bash
# Bounded live SEC check. Never publishes a snapshot; requires a preview root.
python -m edgar_sec.pipelines.metadata_sync.smoke_test \
    --cohort uploaded --artifacts preview/metadata
```

---

## Component Documentation

Every package owns a `README.md` stating its purpose, layout, contracts, public
surface, command surface where it has one, mirrored tests, and deliberate gaps.
The rules that govern them are in [AGENTS.md §5](AGENTS.md), which is normative
where the two disagree.

- **package root** — [edgar_sec](edgar_sec/README.md)
- **foundation** — [foundation](edgar_sec/foundation/README.md) · [checks](edgar_sec/foundation/checks/README.md) · [regex](edgar_sec/foundation/regex/README.md) · [runtime](edgar_sec/foundation/runtime/README.md) · [runtime/settings](edgar_sec/foundation/runtime/settings/README.md) · [scanners](edgar_sec/foundation/scanners/README.md) · [sql](edgar_sec/foundation/sql/README.md) · [text](edgar_sec/foundation/text/README.md)
- **domain** — [domain](edgar_sec/domain/README.md) · [document](edgar_sec/domain/document/README.md) · [document_inventory](edgar_sec/domain/document_inventory/README.md) · [filing_catalog](edgar_sec/domain/filing_catalog/README.md) · [forms](edgar_sec/domain/forms/README.md) · [forms/common](edgar_sec/domain/forms/common/README.md) · [forms/families](edgar_sec/domain/forms/families/README.md) · [submissions](edgar_sec/domain/submissions/README.md) · [taxonomy](edgar_sec/domain/taxonomy/README.md) · [taxonomy/schedules](edgar_sec/domain/taxonomy/schedules/README.md) · [taxonomy/statements](edgar_sec/domain/taxonomy/statements/README.md) · [taxonomy/tables](edgar_sec/domain/taxonomy/tables/README.md)
- **infra** — [infra](edgar_sec/infra/README.md) · [broker](edgar_sec/infra/broker/README.md) · [sec_http](edgar_sec/infra/sec_http/README.md) · [storage](edgar_sec/infra/storage/README.md) · [storage/object_store](edgar_sec/infra/storage/object_store/README.md) · [storage/cohort](edgar_sec/infra/storage/cohort/README.md)
- **engine** — [engine](edgar_sec/engine/README.md) · [company_family](edgar_sec/engine/company_family/README.md) · [index_pages](edgar_sec/engine/index_pages/README.md) · [selection](edgar_sec/engine/selection/README.md) · [submissions](edgar_sec/engine/submissions/README.md)
  - **document** — [document](edgar_sec/engine/document/README.md) · [html](edgar_sec/engine/document/html/README.md) · [page_markers](edgar_sec/engine/document/page_markers/README.md) · [unpacking](edgar_sec/engine/document/unpacking/README.md) · [whitespace](edgar_sec/engine/document/whitespace/README.md)
  - **forms** — [forms](edgar_sec/engine/forms/README.md) · [cover](edgar_sec/engine/forms/cover/README.md) · [cover/boundary](edgar_sec/engine/forms/cover/boundary/README.md) · [cover/checkmarks](edgar_sec/engine/forms/cover/checkmarks/README.md) · [cover/healing](edgar_sec/engine/forms/cover/healing/README.md) · [cover/tables](edgar_sec/engine/forms/cover/tables/README.md) · [cover/toc](edgar_sec/engine/forms/cover/toc/README.md) · [plugins](edgar_sec/engine/forms/plugins/README.md) · [plugins/evaluators](edgar_sec/engine/forms/plugins/evaluators/README.md)
  - **reflow** — [reflow](edgar_sec/engine/reflow/README.md) · [reflow/engine](edgar_sec/engine/reflow/engine/README.md) · [reflow/features](edgar_sec/engine/reflow/features/README.md) · [reflow/rules](edgar_sec/engine/reflow/rules/README.md)
  - **tables** — [tables](edgar_sec/engine/tables/README.md) · [ascii_html](edgar_sec/engine/tables/ascii_html/README.md) · [false_tables](edgar_sec/engine/tables/false_tables/README.md) · [hybrid](edgar_sec/engine/tables/hybrid/README.md) · [policy](edgar_sec/engine/tables/policy/README.md) · [protection](edgar_sec/engine/tables/protection/README.md) · [taxonomy](edgar_sec/engine/tables/taxonomy/README.md)
- **pipelines** — [pipelines](edgar_sec/pipelines/README.md) · [metadata_sync](edgar_sec/pipelines/metadata_sync/README.md) · [filing_catalog](edgar_sec/pipelines/filing_catalog/README.md) · [cohort](edgar_sec/pipelines/cohort/README.md) (including `cohort family-index`) · [document_inventory](edgar_sec/pipelines/document_inventory/README.md) · [document_inventory/snapshot](edgar_sec/pipelines/document_inventory/snapshot/README.md) · [document_storage](edgar_sec/pipelines/document_storage/README.md)
- **apps** — [apps](edgar_sec/apps/README.md) · [viewer](edgar_sec/apps/viewer/README.md)

---

## Repository Layout

```text
edgar_sec/               # each package has its own README.md (linked above)
├── foundation/         # Layer 0: runtime, memory, hashing, serialization, zstd
│                       #   compression, settings registry, scanners, regex DSL
├── domain/             # Layer 1: Cik/Accession, document and inventory records,
│                       #   forms vocabulary, taxonomy and dataset schemas
├── infra/              # Layer 2: SEC HTTP client, broker, atomic IO, DuckDB,
│                       #   Parquet, snapshot manifests, part tree, cohort and object stores
├── engine/             # Layer 3: document and index-page parsing, cover/table
│                       #   processing, candidate selection, submission building
├── pipelines/          # Layer 4: cohort registry (Phase 0), metadata_sync
│                       #   (Phase 1), filing_catalog (Phase 2),
│                       #   document_inventory (streamed plan-to-work-order
│                       #   projection, resumable S4, DAG-backed S5 publication/query),
│                       #   document_storage (Phase 2.5)
└── apps/               # Layer 5: the dataset viewer (read-only, no publishing)

tests/                      # mirrors the edgar_sec/ package tree
├── support.py              # Shared fixture access and offline HTTP test doubles
├── fixtures/               # Committed golden fixtures (cross-layer)
└── <package>/…             # one directory per package, one test file per module

check.py                # Unified repository quality gate runner
run.py                  # Interactive terminal workflow dispatcher
ruff.toml               # Lint configuration (suppressions live here, not in code)
AGENTS.md               # Binding engineering contract and design guidelines
roadmap/                # Multi-phase product roadmap specifications
```

The test tree convention — every test directory is a package, and fixture access
goes through `tests.support` rather than depth arithmetic so reorganizing the
tree does not break test paths — is stated in [AGENTS.md §6](AGENTS.md).

---

## Artifact Layout

All generated paths derive from the artifacts root; no module hardcodes them.

```text
{artifacts_root}/metadata/plans/{plan_id}/plan.json            # Small plan manifest
{artifacts_root}/metadata/plans/{plan_id}/roster/ciks.parquet    # The CIK cohort, frozen into the bundle
{artifacts_root}/metadata/plans/{plan_id}/input/                 # Where the cohort came from
{artifacts_root}/metadata/plans/{plan_id}/assignments/*.parquet   # One chunk set per worker
{artifacts_root}/cohorts/cohorts.sqlite                       # Shared cohort catalog and workspace objects
{artifacts_root}/cohorts/{cohort_id}/ciks.parquet             # Immutable shared CIK dataset
{artifacts_root}/cohorts/family_index/{family_index_id}/company_family.parquet # Immutable published family assignments
{artifacts_root}/cohorts/source_snapshots/{name}/{snapshot_id} # Historical raw payload copies; refresh no longer writes these
{artifacts_root}/transient/metadata/{plan_id}/chunk_NNNN.parquet # Resumable checkpoints
{artifacts_root}/metadata/snapshots/{snapshot_id}/parts/*.parquet   # Published dataset
{artifacts_root}/metadata/snapshots/{snapshot_id}/ciks.parquet     # Published CIK index
{artifacts_root}/metadata/snapshots/catalog.sqlite        # SQLite DAG catalog database

{artifacts_root}/filing_catalog/snapshots/{catalog_id}/     # Immutable catalog snapshot
{artifacts_root}/filing_catalog/snapshots/catalog.sqlite  # SQLite DAG catalog database
{artifacts_root}/filing_catalog/plans/{plan_id}/            # Immutable plan bundle
{artifacts_root}/transient/filing_catalog/{catalog_id}/     # Staging; never published

{artifacts_root}/document_storage/fixtures/{fixture_id}/manifest.json # Common envelope; storage details are pipeline-owned
{artifacts_root}/document_storage/fixtures/{fixture_id}/fixture.sqlite
{artifacts_root}/document_inventory/fixtures/{fixture_id}/manifest.json # Common envelope; index-store details are pipeline-owned
{artifacts_root}/document_inventory/fixtures/{fixture_id}/index_fixtures.sqlite
{artifacts_root}/document_inventory/snapshots/{snapshot_id}/manifest.json # Published inventory snapshot
{artifacts_root}/document_inventory/snapshots/catalog.sqlite      # SQLite DAG catalog database
{artifacts_root}/transient/document_inventory/projection-staging/   # Temporary projection outputs
{artifacts_root}/transient/document_inventory/{run_id}/cohort_accessions.parquet # Normalized cohort facts
{artifacts_root}/transient/document_inventory/{run_id}/cohort_sources.parquet    # Source-CIK edges
{artifacts_root}/transient/document_inventory/{run_id}/work_order.parquet       # Pre-fetch accession work
{artifacts_root}/document_storage/snapshots/{snapshot_id}/  # Published documents
{artifacts_root}/document_storage/review-runs/{run_id}/    # Generated review bundles
{artifacts_root}/transient/document_storage/runs/{run_id}/ # Resumable run staging
```

### Merge Semantics

A merge rejects duplicate or null CIKs, schema drift, plan coverage gaps, row
count mismatches, foreign chunk files, and non-terminal statuses. Duplicate
*accession numbers* are reportable fan-out — the same filing is legitimately
listed by more than one registrant — so they surface as a warning and never
reject. The full contract is in the
[metadata_sync package README](edgar_sec/pipelines/metadata_sync/README.md#contracts-this-package-guarantees).

---

## Engineering Contract

Refer to [`AGENTS.md`](AGENTS.md) for full engineering rules, layer boundary constraints, and verification protocols.
