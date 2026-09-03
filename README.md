# edgar-sec

Transforms SEC filing inputs into versioned, queryable research data
(Parquet / JSONL / SQL) with provenance and resumable runs.

Runtime workers are machine-local and automatically sized from cgroup-aware
available memory using a 512 MiB per-worker estimate and safety budget. Explicit
CLI, environment, or persisted worker values override automatic sizing. Generic
HTTP transport concurrency defaults to 16; SEC uses an 8-request cap separately
from its request-start rate limiter.

Engineering contract and long-term direction live in [`AGENTS.md`](AGENTS.md)
and [`roadmap/master_roadmap.md`](roadmap/master_roadmap.md).

## Repository layout

```text
defs/              # domain-neutral infrastructure (SEC HTTP, storage, runtime, sql, llm, viewer)
phases/            # phase-owned schemas, normalization, planning, validation, merge
 01_metadata_extraction/   # Pipeline A, Part 1 — submissions metadata
 02_filing_extraction/     # Pipeline A, Part 2 — filing catalog and targets (no network)
 025_webpage_storage/      # Phase 2.5 — raw document acquisition and storage
  #   (future) Phase 3 — section extraction from stored documents
roadmap/           # product and extraction specifications
uploads/           # input manifests
.artifacts/        # published manifests and transient runs (git-ignored)
```

## Quick start

```bash
# Run the repository launcher and pick an entry, or dispatch directly:
python run.py                 # interactive menu
python run.py metadata        # Phase 01 interactive wizard
python run.py filing-catalog  # Phase 02 interactive materialize/plan menu
python run.py viewer          # local read-only dataset viewer
python run.py webpage-storage  # Phase 2.5 interactive document acquisition
python run.py append --plan-dir <expanded-plan> --fixture-id <fixture-id>
python run.py settings generate-dotenv   # write a documented .env template

# Or use a component's canonical command surface directly:
.venv/bin/python -m phases.01_metadata_extraction.cli plan \
    --config .artifacts/metadata/config.json
.venv/bin/python -m defs.viewer --artifacts-root .artifacts
# Portable published-artifact transport:
.venv/bin/python -m defs.runtime.bundle create --artifact-id <id> \
    --output artifacts.bundle.zip
# Or choose Artifact Bundle from `python run.py` for the interactive workflow.
```

Settings are declared once as typed specs with logical dotted paths
(`runtime.threads`, `sec.user_agent`, `filing_extraction.source_batch_size`,
`filing_extraction.target_forms`, `filing_extraction.amendment`,
`webpage_storage.zstd_level`, `webpage_storage.mode`);
environment names are generated from them (`RUNTIME_THREADS`,
`FILING_EXTRACTION_SOURCE_BATCH_SIZE`, `FILING_EXTRACTION_TARGET_FORMS`,
`FILING_EXTRACTION_AMENDMENT`). The generated dotenv template
documents every setting, comments out machine-derived suggestions, and never
writes secret values.

## Phases

### [Phase 01 — Submissions Metadata Extraction](phases/01_metadata_extraction/README.md)

Fetches the SEC `data.sec.gov/submissions` feed per CIK, follows historical
submissions files, and produces one `submission_metadata` row per CIK (recent +
 historical filings combined into a nested `filings` list) with strict
 normalization, provenance, and resumable chunk/partition execution.

### [Phase 02 — Filing Catalog](phases/02_filing_extraction/README.md)

Materializes form-partitioned filing occurrences from the finalized Phase 01
artifact without network access or Phase 01 chunk reads, then plans deterministic
target selections for later archive resolution. Phase 02 is no-network metadata
preparation only; it does not fetch filing documents.

Materialization is memory-bounded: source rows are processed in CIK-keyset
batches (configurable, default 1,000) through disk-backed DuckDB staging tables
with machine-derived thread/memory limits (`psutil`, environment-overridable).
Target artifacts are physically unordered; identity and provenance are retained
for later key/sort phases, and staging is transient.

The interactive launcher (`python run.py filing-catalog`) and the canonical CLI
(`python -m phases.02_filing_extraction.cli {materialize,plan,expand,status}`) share one
contract. Filing document acquisition is a separate Phase 2.5 boundary that
consumes these target plans; see the Phase 02 README for the scope split.

### [Phase 2.5 — Webpage Storage](phases/025_webpage_storage/README.md)

Acquires and stores raw SEC filing documents (HTML, SGML, iXBRL) as
content-addressed, zstd-compressed SQLite BLOBs, linked to Phase 02 corporate
occurrences, and applies cover-page normalization (hybrid in-place DOM
preprocessing with layout-table decomposition and text healing). Fixture IDs
are reusable appendable test caches: an expanded child plan reuses existing
blobs and fetches only missing locators. Document parsing and section
extraction are later phases built on the stored and normalized `document_blobs`.
The phase also provides a fixture-ID document corpus review workflow with
20-document batches and exact promoted output goldens.

## Tools

### [Shared Infrastructure (`defs/`)](defs/README.md)

Domain-neutral contracts: SEC HTTP client (pacing/retries/caching), canonical
filing identity (accessions, archive URLs, occurrence IDs, document locator
keys), storage backends, SQL boundary, `sec_forms/` (shared SEC form definitions,
cover-page contracts, and the coordinate-safe `page_markers/` analysis package),
and the shared phase runtime.

### [Dataset Viewer](defs/viewer/README.md)

A local, read-only FastAPI + DuckDB web viewer over the `.artifacts` workspace.
Discovers Parquet/JSONL datasets and JSON documents (plans, manifests, merge
reports), serves schema/stats/paged rows with filter+sort+search, and a guarded
read-only SQL console — with a built TypeScript UI.

The [shared table engine](defs/tables/README.md) provides HTML span-grid
resolution, layout-table unwrapping, financial column healing, standardized
ASCII table generation, and exact tagged-table protection
(`protection.py`) for document-processing phases. Its tracked validated corpus
is stored in one Parquet fixture, with threshold reports written to the shared
`.artifacts/test-runs/` location.

## Conventions

- Every change is gated by the root validation runner: `python check.py` runs
  the ruff format check, the ruff lint (configuration in `ruff.toml`), the
  registered policy scanners (environment-access and future gates — see
  `defs/runtime/checks.py`; `--scan` runs only the scanners), then each test
  suite in isolation; `--fix` applies formatting and safe lint fixes first.
- Shared HTTP, storage, CLI lifecycle, progress, settings, and worker-commit
  behavior live under `defs/`; phases consume those public contracts and own
  their schemas and domain logic. Direct environment access is confined to
  `defs/runtime/env.py` and the settings registry.
- Plans and configs are immutable snapshots validated against effective options;
  completed chunks are skipped and never re-fetched.
- Credentials (SEC User-Agent) come from the environment or the git-ignored
  `.env`; they are never written to plans, manifests, or artifacts.
- Finalized cross-phase artifacts are discovered through immutable manifests in
  `.artifacts/manifests/<phase>/<dataset>/[final|partitions]/`; plans, chunks,
  workers, previews, staging, and merge reports live under
  `.artifacts/transient/<phase>/`. Bundle transport rebases relative paths and
  never stores absolute filesystem paths.
