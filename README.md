# edgar-sec (v2)

High-performance, memory-safe SEC EDGAR extraction engine and pipeline. Transforms SEC submissions and filing disclosures into clean, versioned, queryable columnar datasets (Parquet / Arrow / DuckDB).

---

## Architecture Overview

`edgar_sec` is built from Layer 0 up with strict acyclic downward-only dependencies:

```text
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
# Plan (deterministic, no network):
python run.py metadata plan --input uploads/cik-sec.csv

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

### 5. Filing Catalog Pipeline (Zero Network)

Phase 2 turns a finalized Phase 1 `metadata.parquet` into immutable,
content-addressed **target plans** for a future acquisition phase to consume.
It never performs network I/O, and `tests/test_network_isolation.py` proves
that by walking the import graph rather than by grep.

```bash
# Materialize a catalog snapshot from a Phase 1 snapshot:
python run.py filing-catalog materialize --source <phase1>/metadata.parquet

# Deterministic plan: four filters, no dates, 8-column locator projection.
python run.py filing-catalog plan --catalog current --forms 10-K --amendment original

# Policy plan: fill a declared quota profile. Era-stratified, 18 columns.
python run.py filing-catalog plan --catalog current --scope policy \
    --policy artifacts/filing_catalog/policies/corpus.json
# ...or derive a baseline policy from the catalog's own forms and year range:
python run.py filing-catalog plan --catalog current --scope policy --auto-policy

# Scale a policy plan. The child retains 100% of the parent's locators.
python run.py filing-catalog expand --parent-plan artifacts/filing_catalog/plans/<id> \
    --target-units 10000

# Published state, from manifests only (zero Parquet reads):
python run.py filing-catalog status
```

**Artifact layout.** Snapshots and plans are published immutable; staging lives
under `artifacts_root/transient/`.

```text
artifacts_root/filing_catalog/
├── <catalog_id>/                       # immutable snapshot
│   ├── snapshot.manifest.json
│   ├── company_profiles.parquet        # 23 columns, projected from Phase 1
│   ├── filing_targets/part-00000.parquet
│   └── snapshots/<digest>/             # content-addressed feature snapshot
├── plans/<plan_id>/                    # immutable plan bundle
│   ├── plan.json
│   ├── selection_report.json
│   ├── locator_groups.parquet          # 8 cols (deterministic) or 18 (policy)
│   ├── reserve_targets.parquet         # policy scope only
│   ├── expansion_metadata.json         # child plans only
│   └── targets/form=<FORM>/data.parquet
├── policies/
└── current/pointer.json
```

**Selecting a balanced sample.** The one property that matters most: a corporate
group with 400 subsidiaries files 400 documents, so a naive sample of filings is
mostly that group. Every candidate is keyed by a six-part classification
signature — `(company_family, form, era, sic_code, entity_type, lifecycle_class)`
— and at most `max_per_company_classification` candidates may share one. Because
every subsidiary of a group resolves to one `company_family`, the cap suppresses
the group without special-casing it. A floor the corpus cannot satisfy is
reported in `plan.json` rather than silently absorbed.

### 6. Live Smoke Test (Credential-Gated, Outside the Gate)
```bash
# Bounded live SEC check. Never publishes a snapshot; requires a preview root.
python -m edgar_sec.pipelines.metadata_sync.smoke_test \
    --input tests/fixtures/cik_sec_mini.csv --sample-size 3 --artifacts preview/metadata
```

---

## Repository Layout

```text
edgar_sec/
├── foundation/         # Layer 0: Runtime, memory, hashing, serialization, settings registry, scanners
├── domain/             # Layer 1: Cik, Accession, submission schemas
├── infra/              # Layer 2: SEC HTTP client, token bucket, disk cache, storage
├── engine/             # Layer 3: Submissions normalizer, array unroller, arrow builder
└── pipelines/          # Layer 4: metadata_sync and filing_catalog operators, planners, CLI

tests/                      # Test tree mirrors the edgar_sec/ package tree
├── support.py              # Shared fixture access and offline HTTP test doubles
├── fixtures/               # Committed golden fixtures (cross-layer)
├── foundation/             # hashing, serialization
│   ├── runtime/            # env, memory, paths, settings, partitions, resources
│   └── scanners/           # policy scanner behavior
├── domain/                 # identity
│   └── submissions/         # Arrow schema contract
├── infra/
│   ├── sec_http/           # client, cache, rate_limit, retry
│   └── storage/            # atomic, parquet, duckdb
├── engine/
│   └── submissions/        # normalizer oracle-parity tests
└── pipelines/
    └── metadata_sync/      # manifest, planner, checkpoints, worker, merger,
                            # augmentation, source_registry, end-to-end replay

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
{artifacts_root}/metadata/plans/{plan_id}/plan.json          # Immutable plan
{artifacts_root}/transient/metadata/{plan_id}/chunk_NNNN.parquet  # Resumable checkpoints
{artifacts_root}/metadata/snapshots/{snapshot_id}/metadata.parquet # Published dataset
{artifacts_root}/metadata/snapshots/current/pointer.json     # Current snapshot pointer
{artifacts_root}/metadata/sources/{name}/{snapshot_id}/      # Immutable source snapshots

{artifacts_root}/filing_catalog/<catalog_id>/               # Immutable catalog snapshot
{artifacts_root}/filing_catalog/plans/<plan_id>/             # Immutable plan bundle
{artifacts_root}/filing_catalog/current/pointer.json        # Current catalog pointer
{artifacts_root}/transient/filing_catalog/<catalog_id>/     # Staging; never published
```

### Merge Semantics

Two classes of finding are deliberately distinguished:

- **Failures** — duplicate or null CIKs, schema drift, plan coverage gaps, mismatched row counts, foreign chunk files, non-terminal statuses.
- **Reportable fan-out** — duplicate accessions. The same filing is legitimately listed by more than one registrant, so duplicates are surfaced as a warning and never reject a merge.

---

## Engineering Contract

Refer to [`AGENTS.md`](AGENTS.md) for full engineering rules, layer boundary constraints, and verification protocols.
