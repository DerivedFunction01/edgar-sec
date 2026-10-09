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
> cache roots all derive from the current working directory.

### Interactive Launcher
```bash
# Launch interactive dispatcher menu:
python run.py
```

### Quality Gate
```bash
# Full verification gate (format, lint, scanners, targeted tests):
.venv/bin/python check.py

# Fast static verification during development (skips tests):
.venv/bin/python check.py --fast
```

### Environment Setup
```bash
# Generate documented environment configuration:
python -c "from edgar_sec.foundation.runtime.settings import render_dotenv; print(render_dotenv())" > .env
```

### Pipeline Gateway

Individual pipeline workflows, CLI arguments, and operational contracts are owned
by the respective pipeline package documentation:

| Pipeline | Responsibility | Documentation |
| :--- | :--- | :--- |
| **Cohort Management** | Registrant roster administration, CIK set operations, official source sync | [`pipelines/cohort`](edgar_sec/pipelines/cohort/README.md) |
| **Metadata Sync** | Resumable SEC submissions metadata extraction and snapshot publication | [`pipelines/metadata_sync`](edgar_sec/pipelines/metadata_sync/README.md) |
| **Filing Catalog** | Zero-network DuckDB filing catalog and target planning | [`pipelines/filing_catalog`](edgar_sec/pipelines/filing_catalog/README.md) |
| **Document Inventory** | SEC index page review, projection, and catalog anti-join | [`pipelines/document_inventory`](edgar_sec/pipelines/document_inventory/README.md) |
| **Document Planning** | Offline target-plan generation matching catalog and inventory evidence | [`pipelines/document_planning`](edgar_sec/pipelines/document_planning/README.md) |
| **Document Storage** | Raw document acquisition, normalization, and fixture storage | [`pipelines/document_storage`](edgar_sec/pipelines/document_storage/README.md) |
| **Dataset Viewer** | Operator browser and read-only DuckDB SQL console (Layer 5) | [`apps/viewer`](edgar_sec/apps/viewer/README.md) |

---

## Repository Layout

```text
edgar_sec/               # each package has its own README.md (linked above)
├── foundation/         # Layer 0: runtime, memory, hashing, serialization, zstd
│                       #   compression, settings registry, scanners, regex DSL
├── domain/             # Layer 1: Cik/Accession, document and inventory records,
│                       #   forms vocabulary, taxonomy and dataset schemas
├── infra/              # Layer 2: SEC HTTP client, broker, atomic IO, DuckDB,
│                       #   Parquet, snapshot manifests, part tree, cohort catalog and object store
├── engine/             # Layer 3: document and index-page parsing, cover/table
│                       #   processing, candidate selection, submission building
├── pipelines/          # Layer 4: cohort registry (Phase 0), metadata_sync
│                       #   (Phase 1), explicit cohort diagnostics/maintenance,
│                       #   filing_catalog (Phase 2),
│                       #   document_inventory (streamed plan-to-work-order
│                       #   projection, resumable S4, DAG-backed S5 publication/query),
│                       #   document_planning (offline S6 target plans),
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

All generated paths derive from the artifacts root (`resolve_paths().artifacts_root`).
Path layouts and schemas are owned individually by each pipeline's `paths.py` module
and documented in its respective package README under `## Artifact layout`.

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
