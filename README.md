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

---

## Repository Layout

```text
edgar_sec/
├── foundation/         # Layer 0: Runtime, memory, crypto, settings registry, scanners
├── domain/             # Layer 1: Cik, Accession, submission schemas
├── infra/              # Layer 2: SEC HTTP client, token bucket, disk cache, storage
├── engine/             # Layer 3: Submissions normalizer, array unroller, arrow builder
└── pipelines/          # Layer 4: metadata_sync operator, planner, worker, merger, CLI

tests/
├── foundation/         # Tests for resources, memory, crypto, settings, partitions
├── domain/             # Tests for CIK, accession number, Arrow schemas
├── infra/              # Tests for HTTP client, cache, storage
├── engine/             # Tests for normalizer, unroller, builder with golden fixtures
└── pipelines/          # End-to-end integration and replay tests

check.py                # Unified repository quality gate runner
run.py                  # Interactive terminal workflow dispatcher
AGENTS.md               # Binding engineering contract and design guidelines
roadmap/                # Multi-phase product roadmap specifications
```

---

## Engineering Contract

Refer to [`AGENTS.md`](AGENTS.md) for full engineering rules, layer boundary constraints, and verification protocols.
